export type HighlightSegment = {
  id: string;
  rank?: number;
  start_sec: number;
  end_sec?: number;
  start_time?: string;
  headline?: string;
  reason?: string;
  tags?: string[];
  screenshot_url?: string;
};

export type VodProvider = "twitch" | "youtube";

export type ActivityMapData = {
  bucket_sec?: number;
  duration_sec?: number;
  last_comment_sec?: number;
  buckets?: number[];
};

export type VodData = {
  vod_id: string;
  provider?: VodProvider;
  vod_url?: string;
  title: string;
  published_at: string;
  thumbnail_url?: string;
  duration_sec?: number;
  chat_total?: number;
  comments_per_hour?: number;
  items?: HighlightSegment[];
  activity_map?: ActivityMapData;
};

export type VodIndexEntry = {
  vod_id: string;
  provider?: VodProvider;
  vod_url?: string;
  detail_path: string;
  title?: string;
  published_at?: string;
};

export type VodIndexData = {
  updated_at?: string;
  next_update_at?: string;
  videos?: VodIndexEntry[];
};

export type RuntimeSiteConfig = {
  site?: {
    name?: string;
    description?: string;
    base_url?: string;
    language?: string;
    feedback_url?: string;
    analytics?: {
      goatcounter_code?: string;
    };
  };
  twitch?: {
    channel_login?: string;
  };
};

export type VodPageData = {
  requestedPage: number;
  page: number;
  updatedAt: string;
  nextUpdateAt: string;
  vods: VodData[];
  totalCount: number;
  siteConfig: RuntimeSiteConfig;
};

export const VOD_PAGE_SIZE = 5;
