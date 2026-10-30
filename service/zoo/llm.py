"""LLM 适配层：默认用本地 Qwen2.5-1.5B-Instruct，也可切到任意 OpenAI 兼容端点。

在 Dify 里，这一层由「LLM 节点」承担；本地 demo 为了可复现，用同一条 prompt。
"""
from __future__ import annotations

import json
import os
import re
import threading

_LOCK = threading.Lock()


class LLM:
    def __init__(self):
        self.backend = os.getenv("LLM_BACKEND", "hf")  # hf | openai
        self.model_id = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
        self.device = os.getenv("LLM_DEVICE", "auto")
        self.base_url = os.getenv("OPENAI_BASE_URL", "")
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.model = None
        self.tok = None
        self._dev = "cpu"

    # ---------- 本地 HF ----------
    def _load_local(self):
        with _LOCK:
            if self.model is not None:
                return
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            torch.set_num_threads(int(os.getenv("LLM_THREADS", "32")))
            self.tok = AutoTokenizer.from_pretrained(self.model_id)
            want_cuda = self.device in ("auto", "cuda") and torch.cuda.is_available()
            dtype = torch.float16 if want_cuda else torch.float32
            kwargs = {"dtype": dtype, "low_cpu_mem_usage": True}
            if want_cuda:
                kwargs["device_map"] = "cuda"
            self.model = AutoModelForCausalLM.from_pretrained(self.model_id, **kwargs)
            self.model.eval()
            self._dev = "cuda" if want_cuda else "cpu"

    def _chat_local(self, system: str, user: str, max_new_tokens: int, temperature: float) -> str:
        import torch
        self._load_local()
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        text = self.tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        inputs = self.tok(text, return_tensors="pt").to(self.model.device)
        with torch.inference_mode():
            out = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=temperature > 0,
                temperature=max(temperature, 0.01),
                top_p=0.9,
                repetition_penalty=1.1,
                pad_token_id=self.tok.eos_token_id,
            )
        gen = out[0][inputs["input_ids"].shape[1]:]
        return self.tok.decode(gen, skip_special_tokens=True).strip()

    def _chat_openai(self, system: str, user: str, max_new_tokens: int, temperature: float) -> str:
        import urllib.request
        payload = {
            "model": self.model_id,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_new_tokens,
        }
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.load(r)
        return data["choices"][0]["message"]["content"].strip()

    def chat(self, system: str, user: str, max_new_tokens: int = 420,
             temperature: float = 0.85) -> str:
        if self.backend == "openai" and self.base_url:
            return self._chat_openai(system, user, max_new_tokens, temperature)
        return self._chat_local(system, user, max_new_tokens, temperature)

    def warmup(self) -> dict:
        if self.backend == "openai":
            return {"backend": "openai", "model": self.model_id}
        self._load_local()
        return {"backend": "hf", "model": self.model_id, "device": self._dev,
                "params": self.model.num_parameters()}


def extract_json(text: str) -> dict | None:
    """小模型经常在 JSON 外面裹一层解释，暴力抠第一个平衡的 {...}。"""
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                chunk = text[start:i + 1]
                for attempt in (chunk, re.sub(r",\s*([}\]])", r"\1", chunk)):
                    try:
                        return json.loads(attempt)
                    except json.JSONDecodeError:
                        continue
                return None
    return None
