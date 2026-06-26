export function EmptyStatePanel() {
  return (
    <section className="rounded-2xl border bg-white p-10 text-center">
      <h2 className="text-xl font-semibold">开始一次审阅任务</h2>
      <p className="mt-2 text-sm text-muted-foreground">
        上传底稿文件或粘贴文件链接，并补充审阅要求。系统将抽取表格、校验证据并生成结构化审阅结论。
      </p>
    </section>
  );
}
