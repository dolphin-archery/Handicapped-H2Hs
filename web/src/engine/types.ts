/**
 * TypeScript mirror of the Python bridge's JSON (h2h/bridge.py, UISpec.md section 5).
 *
 * Keys are snake_case end to end, exactly as Python sends them. Display values (scores,
 * percentiles, handicaps, winners) arrive as text formatted by Python; the UI shows them as
 * they are and never formats or recomputes a number itself.
 */

// --- Envelope ------------------------------------------------------------------------------

export type ErrorCode = "validation" | "tiebreak_required" | "state" | "internal";

export interface BridgeError {
  code: ErrorCode;
  message: string;
  /** Stage 2 only: 0-based archer row (null for the event-wide updating parameters). */
  row?: number | null;
  /** Stage 2 only: the offending form field. */
  field?: Stage2Field;
}

export type Envelope<T> = { ok: true; data: T } | { ok: false; error: BridgeError };

// --- The event document, schema version 1 (UISpec.md 5.2) ------------------------------------

export type EventStatus = "setup" | "running" | "complete";
export type SetupMode = "simple" | "advanced";

export interface SharedTarget {
  distance_key: string;
  face_cm: number;
}

export interface ArcherTarget extends SharedTarget {
  face_type: string;
}

export interface EventSetup {
  /** Furthest stage completed: 0 (new) to 3 (Stage 3 confirmed). */
  stage: 0 | 1 | 2 | 3;
  n_archers: number;
  total_arrows: number;
  n_pass: number;
  setup_mode: SetupMode;
  shoot_byes: boolean;
  target: SharedTarget;
  update_handicaps: boolean;
  n_lookback: number | null;
  start_weight: number | null;
}

export interface DocumentArcher {
  name: string;
  bowstyle: string;
  handicap: number;
  target: ArcherTarget | null;
}

export interface StoredMatch {
  /** Schedule position (as text) -> score. */
  scores: Record<string, number>;
  /** Position of the archer closest to the middle, stored only when it decided the pass. */
  closest: number | null;
}

export interface EventDocument {
  schema_version: 1;
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  revision: number;
  status: EventStatus;
  setup: EventSetup;
  archers: DocumentArcher[];
  /** Schedule position -> index into `archers`; null before Stage 2. */
  assignment: number[] | null;
  /** Pass index (text) -> match index (text) -> stored match. */
  scores: Record<string, Record<string, StoredMatch>>;
  current_pass: number;
}

// --- Command inputs --------------------------------------------------------------------------

/** Values typed into a form: text from an input, or a number from a number input. */
export type FormValue = string | number;

export interface Stage1Form {
  n_archers: FormValue;
  total_arrows: FormValue;
  n_pass: FormValue;
  setup_mode: SetupMode;
  /** Simple setup only, e.g. "20yd". */
  distance?: string;
  /** Simple setup only. */
  face_cm?: FormValue;
  shoot_byes?: boolean;
}

export type Stage2Field =
  | "name"
  | "bowstyle"
  | "handicap"
  | "distance"
  | "face_cm"
  | "face_type"
  | "n_lookback"
  | "start_weight";

export interface Stage2Row {
  name: FormValue;
  bowstyle: string;
  handicap: FormValue;
  /** Advanced setup only. */
  distance?: string;
  face_cm?: FormValue;
  face_type?: string;
}

export interface UpdatingForm {
  update_handicaps: boolean;
  n_lookback?: FormValue;
  start_weight?: FormValue;
}

export type ExportKind = "leaderboard_csv" | "archer_results_csv" | "results_pdf";
export type CalculatorKind = "indoor" | "outdoor";

// --- Command results -------------------------------------------------------------------------

export interface Option {
  value: string;
  label: string;
}

export interface Options {
  distance_groups: { group: "Metric" | "Imperial"; items: Option[] }[];
  face_sizes: number[];
  advanced_face_sizes: number[];
  face_types: Option[];
  bowstyles: string[];
  min_handicap: number;
  max_handicap: number;
  defaults: {
    n_archers: number;
    total_arrows: number;
    n_pass: number;
    setup_mode: SetupMode;
    shoot_byes: boolean;
    distance_key: string;
    face_cm: number;
    face_type: string;
    n_lookback: number;
  };
  calculator: {
    kinds: CalculatorKind[];
    rounds: Record<CalculatorKind, Option[]>;
    defaults: Record<CalculatorKind, string>;
  };
}

export interface DocumentResult {
  document: EventDocument;
}

export interface Stage1Result extends DocumentResult {
  passes_per_archer: number;
  /** Passes in the schedule (more than passes per archer when byes are sat out). */
  n_passes: number;
}

/** Stage 2's values from Stage 1 (`stage2_info`, the Flask page's route values). */
export interface Stage2Info {
  n_archers: number;
  setup_mode: SetupMode;
  /** The shared target (simple setup). */
  target: { distance_label: string; face_cm: number; indoor: boolean };
  /** Passes per archer: the start weight's default. */
  default_start_weight: number;
  default_n_lookback: number;
}

export interface Pairings {
  passes: {
    pass_number: number;
    /** `b` is null for a bye (the archer shoots alone). */
    matches: { a: string; b: string | null }[];
    sitting_out: string[];
  }[];
  started: boolean;
}

export interface OverviewMatch {
  index: number;
  names: string[];
  bye: boolean;
  scored: boolean;
  /** "100 - 98", or "-" while unscored. */
  score: string;
  /** "52.1% - 48.0%", or "-". */
  percentiles: string;
  /** A name, or "-" (unscored or a bye). */
  winner: string;
}

export interface Overview {
  pass_index: number;
  pass_number: number;
  n_passes: number;
  n_pass: number;
  matches: OverviewMatch[];
  sitting_out: string[];
  scored_count: number;
  match_count: number;
  pass_complete: boolean;
  is_last: boolean;
  event_complete: boolean;
}

/** One row of a pass table (outputs.PassTableRow), all text. */
export interface PassTableRow {
  archer: string;
  score: string;
  percentile: string;
  start_handicap: string;
  handicap: string;
  /** "Yes", "No", or "-" for a bye. */
  winner: string;
}

export interface MatchView {
  pass_index: number;
  pass_number: number;
  n_passes: number;
  match_index: number;
  bye: boolean;
  archers: { position: number; name: string; max_score: number; score: number | null }[];
  scored: boolean;
  rows: PassTableRow[];
  show_start_handicap: boolean;
  decided_by_closest: boolean;
  closest: number | null;
  next_unscored_match: number | null;
  pass_complete: boolean;
  event_complete: boolean;
}

export interface RecordMatchResult extends DocumentResult {
  match: MatchView;
}

export interface LeaderboardRow {
  archer_index: number;
  rank: string;
  name: string;
  points: string;
  passes_decided: string;
  starting_handicap: string;
  to_date_handicap: string;
}

export interface PairwiseRow {
  archer_a: number;
  archer_b: number;
  name_a: string;
  name_b: string;
  wins_a: string;
  wins_b: string;
  draw: boolean;
  /** "Draw" or "<name> wins". */
  result: string;
}

export interface Results {
  leaderboard: LeaderboardRow[];
  pairwise: PairwiseRow[];
  passes: { pass_index: number; pass_number: number; groups: PassTableRow[][] }[];
  completed_passes: number;
  n_passes: number;
  current_pass_number: number;
  event_complete: boolean;
  show_start_handicap: boolean;
}

export interface ArcherResultRow {
  pass_number: string;
  /** A name, or "bye". */
  opponent: string;
  score: string;
  percentile: string;
  start_handicap: string;
  handicap: string;
}

export interface ArcherSection {
  archer_index: number;
  name: string;
  total_score: string;
  starting_handicap: string;
  to_date_handicap: string;
  rows: ArcherResultRow[];
  average: { score: string; percentile: string; start_handicap: string; handicap: string } | null;
}

export interface ArcherResults {
  sections: ArcherSection[];
  completed_passes: number;
  n_passes: number;
  show_start_handicap: boolean;
}

export interface ChartArcher {
  name: string;
  legend: string;
  passes: { index: number; score: number }[];
}

/** chart_data.build_pair_chart_data, plotted as it is. */
export interface PairChart {
  archer_a: ChartArcher;
  archer_b: ChartArcher;
  distribution_a: { x: number; y: number }[];
  distribution_b: { x: number; y: number }[];
  x_min: number;
  x_max: number;
  y_max: number;
  current_pass: number;
}

export interface ExportFile {
  filename: string;
  mime_type: string;
  encoding: "utf-8" | "base64";
  content: string;
}

export interface CalculatorResult {
  handicap: number;
  /** The handicap as the page shows it, e.g. "49.3". */
  text: string;
}

// --- The command table: name -> payload and result ---------------------------------------------

export interface Commands {
  options: { payload: Record<string, never>; result: Options };
  new_document: { payload: { event_id: string; now_iso: string }; result: EventDocument };
  apply_stage1: { payload: { doc: EventDocument; form: Stage1Form }; result: Stage1Result };
  stage2_info: { payload: { doc: EventDocument }; result: Stage2Info };
  apply_stage2: {
    payload: { doc: EventDocument; archers: Stage2Row[]; updating: UpdatingForm; seed: number };
    result: DocumentResult;
  };
  redraw: { payload: { doc: EventDocument; seed: number }; result: DocumentResult };
  pairings: { payload: { doc: EventDocument }; result: Pairings };
  start_event: { payload: { doc: EventDocument }; result: DocumentResult };
  overview: { payload: { doc: EventDocument }; result: Overview };
  match: { payload: { doc: EventDocument; match_index: number }; result: MatchView };
  record_match: {
    payload: {
      doc: EventDocument;
      match_index: number;
      scores: Record<string, FormValue>;
      closest: number | null;
    };
    result: RecordMatchResult;
  };
  advance: { payload: { doc: EventDocument }; result: DocumentResult };
  results: { payload: { doc: EventDocument }; result: Results };
  archer_results: { payload: { doc: EventDocument }; result: ArcherResults };
  pair_chart: { payload: { doc: EventDocument; a: number; b: number }; result: PairChart };
  export: {
    payload: { doc: EventDocument; kind: ExportKind; now_iso: string };
    result: ExportFile;
  };
  calculator: {
    payload: { kind: CalculatorKind; round_codename: string; compound: boolean; score: FormValue };
    result: CalculatorResult;
  };
  validate_document: { payload: { raw: unknown }; result: EventDocument };
}

export type CommandName = keyof Commands;
export type PayloadOf<C extends CommandName> = Commands[C]["payload"];
export type ResultOf<C extends CommandName> = Commands[C]["result"];
