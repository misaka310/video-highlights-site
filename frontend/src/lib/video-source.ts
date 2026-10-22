const HLS_PATTERN = /\.m3u8($|[?#])/i;

export function isHlsSource(url: string): boolean {
  return HLS_PATTERN.test(String(url || "").trim());
}
