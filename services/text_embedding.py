# utils/embedding_matcher.py

import numpy as np
import faiss
import os
import pickle
from config.model_provider import create_embedding_model


def find_best_match_indices(text: str, candidates: list) -> list:
    """
    输入一个text和一个候选列表，通过embedding和index技术返回所有候选项的索引，按相似度从高到低排序
    :param text: 待匹配文本
    :param candidates: 候选文本列表
    :param embed_fn: 一个将文本转为embedding的函数
    :return: 所有候选项的索引列表，按相似度从高到低排序
    """
    if not candidates:
        return []
    candidate_embs = [embed_input(c) for c in candidates]
    candidate_embs = np.array(candidate_embs).astype("float32")
    dimension = candidate_embs.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(candidate_embs)
    text_emb = np.array([embed_input(text)]).astype("float32")
    k = len(candidates)
    _, indices = index.search(text_emb, k)
    return indices[0][:k].tolist()


def embed_input(input_text: str, timeout: float | None = None) -> list:
    """把一段文本转成向量（**同步**版本）。

    ⚠ **在 async 上下文里请用 ``aembed_input``。** 本函数内部是同步阻塞的 HTTP 请求，
    从协程里调用会占住整个事件循环——期间同进程所有协程（含 IM 长连接的收包与心跳）
    全部停摆，且 ``asyncio.wait_for`` 之类的外层超时也**无法生效**（定时器回调都跑不了）。
    本函数只应用于确实不在事件循环关键路径上的同步调用点，如
    ``find_best_match_indices``。

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
