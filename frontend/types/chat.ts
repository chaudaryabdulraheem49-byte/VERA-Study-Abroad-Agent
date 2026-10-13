/**
 * Wire contract with the FastAPI backend.
 *
 * These mirror `backend/app/schemas.py` — SSEEventType, OnboardingSlots,
 * ExtractedTranscript and DiagnosticCardPayload. Keep both sides in step.
 */

export type SlotName =
  | "full_name"
  | "nationality"
  | "cgpa"
  | "field_of_study"
  | "education_level"
  | "target_country"
  | "language_score";

export type EducationLevel =
  | "high_school"
  | "diploma"
  | "bachelors"
  | "masters"
  | "doctorate";

export const EDUCATION_LEVEL_LABELS: Record<EducationLevel, string> = {
  high_school: "Intermediate / High school",
  diploma: "Diploma",
  bachelors: "Bachelor's",
  masters: "Master's",
  doctorate: "Doctorate",
};

export type GradingScale =
  | "percentage"
  | "us_4_0"
  | "scale_5_0"
  | "scale_10_0"
  | "scale_20_0"
  | "german_1_5"
  | "unknown";

export interface AcademicScore {
  raw_value: number;
  scale: GradingScale;
  scale_max: number | null;
  scale_min_pass: number | null;
}

export interface LanguageScore {
  test: "IELTS" | "TOEFL" | "PTE" | "DUOLINGO" | "NONE" | "PLANNED";
  overall: number | null;
  planned_date: string | null;
}

export interface OnboardingSlots {
  full_name: string | null;
  nationality: string | null;
  cgpa: AcademicScore | null;
  field_of_study: string | null;
  education_level: EducationLevel | null;
  target_country: string | null;
  /** Further confirmed destinations; `target_country` stays the primary. */
  extra_countries: string[];
  language_score: LanguageScore | null;
}

export interface SlotUpdatePayload {
  session_id: string;
  slots: OnboardingSlots;
  filled: SlotName[];
  missing: SlotName[];
  pending_confirmation: SlotName[];
  is_complete: boolean;
}

export interface SubjectGrade {
  name: string;
  grade: string | null;
  credits: number | null;
  numeric_grade: number | null;
  passed: boolean | null;
}

export interface ExtractedTranscript {
  student_name: string | null;
  institution_name: string | null;
  program_name: string | null;
  field_of_study: string | null;
  subjects: SubjectGrade[];
  cumulative_gpa: number | null;
  gpa_scale_max: number | null;
  percentage: number | null;
  grading_scale: GradingScale;
  total_credits: number | null;
  backlogs: number;
  failed_subjects: string[];
  gap_years: number | null;
  graduation_year: number | null;
  confidence: number;
  parser: "gpt4o_vision" | "gemini_vision" | "llamaparse" | "unknown";
  /** True when no overall grade was printed and one was averaged instead. */
  cumulative_gpa_computed?: boolean;
  warnings: string[];
}

export type UKClassification =
  | "First Class Honours"
  | "Upper Second Class (2:1)"
  | "Lower Second Class (2:2)"
  | "Third Class Honours"
  | "Below Honours / Fail";

export interface GradeConversion {
  source_value: number;
  source_scale: GradingScale;
  normalized_percentage: number;
  us_gpa: number;
  us_letter: string;
  german_grade: number;
  german_label: string;
  german_formula: string;
  uk_classification: UKClassification;
  ects_grade: string;
  assumptions: string[];
}

export interface DiagnosticCardPayload {
  session_id: string;
  student_name: string | null;
  institution_name: string | null;
  field_of_study: string | null;
  education_level: string | null;
  target_country: string | null;
  conversion: GradeConversion;
  backlogs: number;
  gap_years: number | null;
  total_credits: number | null;
  subject_count: number;
  eligibility_notes: string[];
  generated_at: number;
}

/** One ranked programme. Mirrors `CourseMatch` in the Phase 2 schemas. */
export interface UniversityMatch {
  course_id: string;
  course_title: string;
  university_name: string;
  country: string;
  degree_level: string;
  tuition_fee_usd: number;
  currency: string;
  tuition_fee_amount: number;
  /** null means the source states no requirement - not a requirement of zero. */
  min_gpa_percent: number | null;
  min_ielts_score: number | null;
  deadline_date: string | null;
  /** "published" | "rolling" | "not_published" */
  deadline_type?: string | null;
  intakes?: string | null;
  post_study_work_eligible: boolean;
  syllabus_description: string;
  /** Qdrant cosine score; higher is a closer syllabus match. */
  similarity_score: number;
}

/**
 * Typical entry requirements for the destination country - general guidance,
 * never a particular programme's stated bar. Present only when at least one
 * shown course publishes no requirement of its own.
 */
export interface MatchGuidance {
  country: string;
  typical_gpa_percent: number;
  typical_ielts: number;
  note: string;
  unstated_count: number;
  student_clears: boolean | null;
}

export interface UniversityMatchesPayload {
  session_id: string;
  query: string;
  matches: UniversityMatch[];
  /** Set only when `matches` is empty: why the index had nothing. */
  note?: string | null;
  /** True when nothing in the student's own subject cleared the bar, so these
   *  come from neighbouring disciplines. */
  from_related_fields?: boolean;
  guidance?: MatchGuidance | null;
}

/** Discriminated union of every frame the backend can send. */
export type ServerEvent =
  | { event: "text_delta"; data: { text: string } }
  | { event: "status"; data: { stage: string; message: string } }
  | { event: "slot_update"; data: SlotUpdatePayload }
  | { event: "transcript_parsed"; data: ExtractedTranscript }
  | { event: "diagnostic_card"; data: DiagnosticCardPayload }
  | { event: "university_matches"; data: UniversityMatchesPayload }
  | { event: "error"; data: { message: string; recoverable?: boolean } }
  | { event: "done"; data: { session_id: string; diagnostics_unlocked?: boolean } };

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** Attachments rendered beneath the bubble. */
  card?: DiagnosticCardPayload;
  matches?: UniversityMatchesPayload;
  transcript?: ExtractedTranscript;
  fileName?: string;
  error?: string;
  pending?: boolean;
}

export const SLOT_ORDER: SlotName[] = [
  "full_name",
  "nationality",
  "cgpa",
  "field_of_study",
  "education_level",
  "target_country",
  "language_score",
];

export const SLOT_LABELS: Record<SlotName, string> = {
  full_name: "Full name",
  nationality: "Nationality",
  cgpa: "CGPA / grade",
  field_of_study: "Field of study",
  education_level: "Level of study",
  target_country: "Target country",
  language_score: "IELTS / TOEFL",
};

const SCALE_SUFFIX: Record<GradingScale, string> = {
  percentage: "%",
  us_4_0: "/4.0",
  scale_5_0: "/5.0",
  scale_10_0: "/10.0",
  scale_20_0: "/20.0",
  german_1_5: " (DE)",
  unknown: "",
};

/** Human-readable one-liner for a filled slot, used by the checklist. */
export function describeSlot(
  slot: SlotName,
  slots: OnboardingSlots,
): string | null {
  switch (slot) {
    case "cgpa": {
      const value = slots.cgpa;
      return value ? `${value.raw_value}${SCALE_SUFFIX[value.scale] ?? ""}` : null;
    }
    case "education_level": {
      const value = slots.education_level;
      return value ? (EDUCATION_LEVEL_LABELS[value] ?? value) : null;
    }
    case "language_score": {
      const value = slots.language_score;
      if (!value) return null;
      if (value.test === "PLANNED") return "Planned";
      if (value.test === "NONE") return "Not taken";
      return value.overall === null ? value.test : `${value.test} ${value.overall}`;
    }
    case "target_country": {
      // Shown as one line: a student who asked for two destinations should
      // see both in their profile, not just the one that led.
      const all = [slots.target_country, ...(slots.extra_countries ?? [])].filter(
        Boolean,
      );
      return all.length > 0 ? all.join(", ") : null;
    }
    default:
      return slots[slot];
  }
}
