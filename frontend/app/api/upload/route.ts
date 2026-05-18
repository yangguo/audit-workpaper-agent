import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const MAX_FILES = 10;
const MAX_FILE_SIZE = 100 * 1024 * 1024;
const MAX_TOTAL_SIZE = 200 * 1024 * 1024;

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:5000";

    let totalSize = 0;
    let fileCount = 0;

    const backendForm = new FormData();
    for (const [key, value] of formData.entries()) {
      if (value instanceof File) {
        fileCount += 1;
        totalSize += value.size;
        if (fileCount > MAX_FILES) {
          return NextResponse.json({ error: "Too many files" }, { status: 400 });
        }
        if (value.size > MAX_FILE_SIZE) {
          return NextResponse.json({ error: "File too large" }, { status: 413 });
        }
        if (totalSize > MAX_TOTAL_SIZE) {
          return NextResponse.json({ error: "Total upload too large" }, { status: 413 });
        }
        backendForm.append(key, value, value.name);
      } else {
        backendForm.append(key, String(value));
      }
    }

    const res = await fetch(`${backendUrl}/upload`, {
      method: "POST",
      body: backendForm,
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    return NextResponse.json({ error: "Upload proxy error" }, { status: 500 });
  }
}
