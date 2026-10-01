"""Opt-in fused attention for segment timestamps; never retain a class patch."""
from contextlib import contextmanager
import threading

_LOCK = threading.RLock()


def fused_qkv_attention(self, q, k, v, mask=None):
    import mlx.core as mx
    batch, context, state = q.shape
    scale = (state // self.n_head) ** -0.25
    # Preserve the installed Whisper implementation's fp16 input scaling and
    # sliced additive mask, including its one-token KV-cache broadcast.
    q = q.reshape(*q.shape[:2], self.n_head, -1).transpose(0, 2, 1, 3) * scale
    k = k.reshape(*k.shape[:2], self.n_head, -1).transpose(0, 2, 1, 3) * scale
    v = v.reshape(*v.shape[:2], self.n_head, -1).transpose(0, 2, 1, 3)
    mask = mask[:context, :context] if mask is not None else None
    output = mx.fast.scaled_dot_product_attention(q, k, v, scale=1.0, mask=mask)
    return output.transpose(0, 2, 1, 3).reshape(batch, context, state), None


@contextmanager
def attention_scope(enabled=False, word_timestamps=False):
    if enabled and word_timestamps:
        raise ValueError('實驗快速注意力不支援 word_timestamps，需要原始 cross QK')
    # Baseline and Taiwanese inference also take this lock, preventing them
    # from observing another concurrent request's temporary class patch.
    with _LOCK:
        if not enabled:
            yield
            return
        from mlx_whisper.whisper import MultiHeadAttention
        original = MultiHeadAttention.qkv_attention
        MultiHeadAttention.qkv_attention = fused_qkv_attention
        try:
            yield
        finally:
            MultiHeadAttention.qkv_attention = original
