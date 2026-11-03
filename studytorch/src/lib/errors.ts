import { NextResponse } from "next/server";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number = 500,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function describe(error: unknown): { message: string; status: number } {
  if (error instanceof ApiError) {
    return { message: error.message, status: error.status };
  }
  if (error instanceof Error) {
    return { message: error.message, status: 500 };
  }
  return { message: "未知错误", status: 500 };
}

export function toErrorResponse(error: unknown): NextResponse {
  const { message, status } = describe(error);
  console.error("[studyseek]", message);
  return NextResponse.json({ error: message }, { status });
}
