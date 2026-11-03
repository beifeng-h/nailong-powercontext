import { ACCEPTED_EXTENSIONS, MAX_UPLOAD_BYTES } from "@/lib/config";
import { ApiError } from "@/lib/errors";

export interface UploadInput {
  fileName: string;
  bytes: Buffer;
}

export type SupportedKind = "pdf" | "markdown" | "text";

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

export function kindOf(name: string): SupportedKind {
  const ext = extensionOf(name);
  if (ext === ".pdf") return "pdf";
  if (ext === ".md" || ext === ".markdown") return "markdown";
  if (ext === ".txt") return "text";
  throw new ApiError(`不支持的文件类型：${name || "(未命名)"}，仅支持 ${ACCEPTED_EXTENSIONS.join(" / ")}`, 415);
}

export function validateUpload(name: string, bytes: Buffer): void {
  kindOf(name);
  if (bytes.byteLength === 0) {
    throw new ApiError(`文件内容为空：${name}`, 400);
  }
  if (bytes.byteLength > MAX_UPLOAD_BYTES) {
    throw new ApiError(`文件超过 ${Math.round(MAX_UPLOAD_BYTES / 1024 / 1024)}MB 上限：${name}`, 413);
  }
}

/** PDF / Markdown / TXT -> 纯文本。 */
export async function extractText(input: UploadInput): Promise<string> {
  const kind = kindOf(input.fileName);

  if (kind === "pdf") {
    const { default: pdfParse } = await import("pdf-parse/lib/pdf-parse.js");
    const result = await pdfParse(input.bytes);
    return result.text ?? "";
  }

  return new TextDecoder("utf-8").decode(input.bytes).replace(/^\uFEFF/, "");
}
