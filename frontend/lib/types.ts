// API response types — mirror of the backend Pydantic schemas.

export type SearchStatus = "queued" | "running" | "completed" | "failed";

export interface SearchProgress {
  found?: number;
  to_process?: number;
  processed?: number;
  kept?: number;
  /** Hourly scrape budget, reported up front so a stall is visible before it happens. */
  budget_used?: number;
  budget_limit?: number;
  budget_remaining?: number;
  /** Set when the run stopped early because the hourly budget was spent. */
  rate_limited?: boolean;
  retry_after_s?: number;
  /** Set when the run stopped because the platform locked the account. */
  account_restricted?: boolean;
  /** Human-readable explanation of whichever stop condition fired. */
  note?: string;
  /** Wall-clock seconds: the provider search, and the run end to end. */
  search_seconds?: number;
  elapsed_seconds?: number;
  seconds_per_profile?: number;
  /** How many candidates were actually returned after filtering. */
  returned?: number;
  /** How many profiles were read and then filtered out, and the commonest
   *  reasons why — so an empty shortlist can name the filter to loosen
   *  instead of asking the recruiter to guess. */
  rejected?: number;
  rejection_reasons?: string[];
  /** How many profiles could not be opened at all. */
  failed_profiles?: number;
}

/** Something the run was asked to do and could not.
 *
 *  Distinct from an error: the search finished and may well have returned
 *  candidates — they just answer a different question than the one asked. A
 *  Big Four search whose company filter never reached LinkedIn returns real
 *  people from the wrong firms, and saying nothing about that is how the app
 *  spent a week telling recruiters their criteria were too strict. */
export interface Degradation {
  kind: string;
  detail: string;
}

export interface Search {
  id: string;
  job_title: string;
  critical_skills: string[];
  location: string | null;
  min_experience: number;
  require_title_match?: boolean;
  graduation_year_from?: number | null;
  graduation_year_to?: number | null;
  keywords: string[];
  companies: string[];
  company_ids: string[];
  location_ids: string[];
  industry: string | null;
  max_results: number;
  min_match_score: number;
  enforce_location: boolean;
  provider: string;
  score_version: string;
  status: SearchStatus;
  progress: SearchProgress;
  error: string | null;
  degraded_reasons: Degradation[] | null;
  result_count: number;
  created_at: string;
  completed_at: string | null;
}

export interface CandidateSummary {
  id: string;
  name: string;
  headline: string | null;
  current_title: string | null;
  current_company: string | null;
  location: string | null;
  total_experience_years: number;
  profile_picture_url: string | null;
  source: string;
  source_profile_url: string;
  skills: string[];
  top_skills: string[];
}

export interface ExperienceEntry {
  title?: string | null;
  company?: string | null;
  start?: string | null;
  end?: string | null;
  location?: string | null;
  description?: string | null;
}

export interface EducationEntry {
  school?: string | null;
  degree?: string | null;
  field?: string | null;
  start?: string | null;
  end?: string | null;
}

export interface Candidate extends CandidateSummary {
  about: string | null;
  experience: ExperienceEntry[];
  education: EducationEntry[];
  licenses: Record<string, unknown>[];
  certifications: Record<string, unknown>[];
  languages: string[];
  fetched_at: string;
}

export interface ScoreBreakdown {
  title: number;
  keywords: number;
  experience: number;
  location: number;
}

export interface SearchResult {
  id: string;
  candidate: CandidateSummary;
  match_score: number;
  score_version: string;
  score_breakdown: ScoreBreakdown;
  matched_keywords: string[];
  missing_keywords: string[];
  reasons: string[];
  rank: number;
}

export interface SavedCandidate {
  id: string;
  candidate: CandidateSummary;
  notes: string | null;
  created_at: string;
}

export interface SkillCount {
  skill: string;
  count: number;
}

export interface DashboardStats {
  total_searches: number;
  completed_searches: number;
  running_searches: number;
  saved_candidates: number;
  total_candidates_found: number;
  average_match_score: number;
  top_skills: SkillCount[];
  recent_searches: Search[];
}

export type ProviderAccountStatus = "active" | "restricted" | "retired";

export interface ProviderAccount {
  provider: string;
  status: ProviderAccountStatus;
  has_session: boolean;
  status_reason: string | null;
  /** How many accounts have already been burned on this provider. */
  retired_count: number;
}

export interface SearchCreateInput {
  job_title: string;
  critical_skills: string[];
  location?: string | null;
  min_experience: number;
  require_title_match?: boolean;
  graduation_year_from?: number | null;
  graduation_year_to?: number | null;
  keywords: string[];
  companies?: string[];
  /** LinkedIn's own resolved ids, taken from a pasted search URL. The reliable
   *  way to filter — LinkedIn picked the entities, so they cannot be wrong. */
  company_ids?: string[];
  location_ids?: string[];
  industry?: string | null;
  max_results: number;
  min_match_score: number;
  enforce_location: boolean;
  provider?: string;
}
