import { apiFetch } from "./client";

export interface StagedUpload {
  upload_id: string;
  file_name: string;
}

/**
 * Stage a resume PDF over HTTP. The chat socket then references it by id, so a
 * multi-megabyte body never travels as base64 through the chat channel.
 */
export async function uploadResume(file: File): Promise<StagedUpload> {
  const body = new FormData();
  body.append("file", file);

  return apiFetch<StagedUpload>("/api/v1/chat/upload", { method: "POST", body });
}