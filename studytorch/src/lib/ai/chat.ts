import { dashscope } from "@/lib/config";
import { ApiError } from "@/lib/errors";
import { buildTerms, excerpt } from "@/lib/highlight";
import type { AnswerSource } from "@/lib/types";

const SYSTEM_PROMPT = `你是 StudySeek 学习资料库助手。
要求：
1. 只依据下面提供的资料片段回答，用 [1]、[2] 这样的编号标注引用来源。
2. 资料片段里没有的内容不要编造；资料不足时直接说明不足，并建议用户换关键词检索。
3. 用简体中文回答，先给结论，再分点展开。`;

/** 控制进入 Prompt 的上下文体量，避免长文档把 token 撑爆。 */
function contextBlock(sources: AnswerSource[], perSnippet = 600): string {
  return sources
    .map((source) => {
      const text = source.content.replace(/\s+/g, " ").slice(0, perSnippet);
      return `[${source.index}] 《${source.fileName}》（分类：${source.category}）\n${text}`;
    })
    .join("\n\n");
}

interface ChatResponse {
  choices?: { message?: { content?: string } }[];
  error?: { message?: string };
  message?: string;
}

let warnedChatFallback = false;

function warnChatFallbackOnce(): void {
  if (warnedChatFallback) return;
  warnedChatFallback = true;
  console.warn(
    "[studyseek] DASHSCOPE_API_KEY 未配置：AI 问答已降级为「检索片段抽取式回答」，不会调用 qwen-turbo；答案只是原文拼接，不做归纳或推理。",
  );
}

/**
 * 无 Key 时的抽取式回答：按检索排序取最相关的几段原文，围绕问题关键词截取上下文，
 * 明确标注降级模式，避免让用户误以为是 qwen-turbo 生成的答案。
 */
function extractiveAnswer(question: string, sources: AnswerSource[]): string {
  const terms = buildTerms(question);
  const top = sources.slice(0, 3);

  const blocks = top.map((source) => {
    const text = excerpt(source.content.replace(/\s+/g, " ").trim(), terms, 220);
    return `[${source.index}] 《${source.fileName}》（分类：${source.category}）\n${text}`;
  });

  return [
    "【本地降级模式】未配置 DASHSCOPE_API_KEY，以下回答由检索到的资料片段原文抽取拼接而成，未经 qwen-turbo 生成或归纳。",
    "",
    `资料库中与「${question}」最相关的原文片段（按检索相关度排序）：`,
    "",
    blocks.join("\n\n"),
    "",
    "如需综合归纳式的回答，请在 .env 中配置 DASHSCOPE_API_KEY 后重启服务。",
  ].join("\n");
}

export async function generateAnswer(question: string, sources: AnswerSource[]): Promise<string> {
  if (sources.length === 0) {
    return "资料库里没有检索到相关内容，无法回答。可以先在首页上传学习资料，或换一个更具体的关键词再试。";
  }

  if (!dashscope.apiKeyConfigured()) {
    warnChatFallbackOnce();
    return extractiveAnswer(question, sources);
  }

  const response = await fetch(`${dashscope.baseUrl}/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${dashscope.apiKey()}`,
    },
    body: JSON.stringify({
      model: dashscope.chatModel,
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        {
          role: "user",
          content: `资料片段：\n\n${contextBlock(sources)}\n\n问题：${question}`,
        },
      ],
      temperature: 0.3,
      stream: false,
    }),
  });

  const payload = (await response.json().catch(() => ({}))) as ChatResponse;
  const answer = payload.choices?.[0]?.message?.content?.trim();

  if (!response.ok || !answer) {
    const reason = payload.error?.message ?? payload.message ?? `HTTP ${response.status}`;
    throw new ApiError(`大模型调用失败（${dashscope.chatModel}）：${reason}`, 502);
  }

  return answer;
}
