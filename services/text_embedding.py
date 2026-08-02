# utils/embedding_matcher.py

import asyncio

import numpy as np
import faiss
import os
import pickle
from config.model_provider import create_embedding_model


async def afind_best_match_indices(text: str, candidates: list) -> list:
    """把 text 与候选列表做向量相似度匹配，返回候选下标、按相似度从高到低排序。

    Args:
        text: 待匹配文本（如用户说的"力气大"，或某位技师的专长）。
        candidates: 候选文本列表（如各技师的 strength 字段）。

    Returns:
        候选项的下标列表，按相似度从高到低；``candidates`` 为空时返回 ``[]``。

    **为什么是 ``gather`` 而不是 ``for c in candidates: await aembed_input(c)``**：
    串行 await 虽然不会冻住事件循环（每次 await 都让出控制权），但延迟会累加成
    ``N × RTT``。N 是门店技师数、每次请求上限秒级，串行很容易超过 agent loop 的工具
    超时而被整体掐断——**功能上等价于失败**。并发发起则整体约 1 轮 RTT。

    **为什么顺序是对的**：``asyncio.gather`` 按**传入顺序**返回结果，而非完成顺序。
    故 ``embs[i]`` 恒对应 ``candidates[i]``，FAISS 里的索引位与候选下标一一对应，
    排序结果不会因为"谁先返回"而漂移。这是本函数可以并发化的前提，改动时勿破坏。

    **失败语义**：``gather`` 默认 ``return_exceptions=False``，任一候选向量化失败即
    整体抛出——与改造前串行循环中途抛出的行为一致，由调用方（agent loop 的
    ``_dispatch``）吞成「工具执行失败」回灌。刻意不做部分降级：那会让"部分候选没有
    向量"变成匹配逻辑里的一个新状态，把缺陷修复变成行为变更。
    """
    if not candidates:
        return []
    # 查询与全部候选一次性并发发出：共 N+1 个请求、约 1 轮 RTT。
    # 解包时第一个是查询向量，其余按候选顺序对应。
    query_emb, *candidate_embs = await asyncio.gather(
        aembed_input(text), *(aembed_input(c) for c in candidates)
    )
    candidate_arr = np.array(candidate_embs).astype("float32")
    dimension = candidate_arr.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(candidate_arr)
    text_arr = np.array([query_emb]).astype("float32")
    k = len(candidates)
    _, indices = index.search(text_arr, k)
    return indices[0][:k].tolist()


def embed_input(input_text: str, timeout: float | None = None) -> list:
    """把一段文本转成向量（**同步**版本）。

    ⚠ **在 async 上下文里请用 ``aembed_input``。** 本函数内部是同步阻塞的 HTTP 请求，
    从协程里调用会占住整个事件循环——期间同进程所有协程（含 IM 长连接的收包与心跳）
    全部停摆，且 ``asyncio.wait_for`` 之类的外层超时也**无法生效**（定时器回调都跑不了）。

    **当前没有生产调用方**，保留它是作为"为什么必须有异步版"的可执行对照——
    ``tests/test_embedding_timeout.py::test_sync_version_is_not_cancellable_by_design``
    用它把「同步调用在 ``wait_for`` 下取消不掉」这个反直觉结论钉成证据。删掉函数，
    那条证据也就没了（见 change ``fix-technician-embedding-blocking`` 的 design D3）。

    📌 **这段 docstring 曾经写错过，教训值得留**：原文说"本函数只应用于确实不在事件
    循环关键路径上的同步调用点，如 ``find_best_match_indices``"——而那个例子恰恰在
    关键路径上（``find_technician`` 工具的 async handler 一路同步调下来），正是它让
    这个缺陷躲过了 ``fix-embedding-timeout-blocking`` 那次修复。**判断"是否在事件循环
    关键路径"必须沿调用链查到入口，不能只看直接调用者，更不能靠注释自我背书。**

    Args:
        input_text: 待向量化的文本。
        timeout: 请求超时秒数；缺省取 ``EMBEDDING_TIMEOUT_SECONDS`` / 20 秒。

    历史说明：本函数曾声明 ``timeout: int = 600`` 却**从未使用**它，同时
    ``create_embedding_model()`` 也不传超时，于是实际落到 openai 客户端默认的 600 秒
    ——那个 600 只是对默认值的无效复述。曾声明的 ``model`` / ``encoding_format`` /
    ``dimensions`` 三个参数同样从未生效（模型名来自 ``EMBEDDING_MODEL`` 环境变量），
    故一并删除：留着不生效的参数比没有更糟，调用方会以为自己控制了什么。
    """
    embeddings = create_embedding_model(timeout=timeout)
    return embeddings.embed_query(input_text)


async def aembed_input(input_text: str, timeout: float | None = None) -> list:
    """把一段文本转成向量（**异步**版本，async 上下文一律用这个）。

    走 LangChain 的原生 ``aembed_query`` 而非 ``asyncio.to_thread(embed_input, ...)``：
    后者能让事件循环不被阻塞，但线程里的同步调用**依然不可取消**——超时后协程被取消，
    那个线程仍会在后台跑到自己结束，连接与线程都泄漏。原生异步走 httpx 的异步栈，
    取消是真取消。见 change ``fix-embedding-timeout-blocking`` 的 design D2。

    Args:
        input_text: 待向量化的文本。
        timeout: 请求超时秒数；缺省取 ``EMBEDDING_TIMEOUT_SECONDS`` / 20 秒。
    """
    embeddings = create_embedding_model(timeout=timeout)
    return await embeddings.aembed_query(input_text)


def save_technician_embeddings(embeddings, indices, path="data/technician_embeddings.pkl"):
    """
    保存技师嵌入向量和索引到本地
    """
    with open(path, "wb") as f:
        pickle.dump({"embeddings": embeddings, "indices": indices}, f)


def load_technician_embeddings(path="data/technician_embeddings.pkl"):
    """
    加载本地保存的技师嵌入向量和索引
    """
    if not os.path.exists(path):
        return None, None
    with open(path, "rb") as f:
        data = pickle.load(f)
        return data.get("embeddings"), data.get("indices")
