"use client";

export function DateStamp() {
  const now = new Date();
  const formattedDate = new Intl.DateTimeFormat("en", {
    day: "2-digit",
    month: "long",
    year: "numeric",
  }).format(now);

  return (
    <time dateTime={now.toISOString()} suppressHydrationWarning>
      {formattedDate}
    </time>
  );
}
