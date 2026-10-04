import { useCallback, useEffect, useRef, useState } from "react";
import { DraftSaver, deleteDraft, getDraft, setDraft } from "../storage/autosave";
import { useServices } from "./services";

/** An event's drafts: one entry per form ("stage1", "stage2", "match:<pass>:<match>"). */
export type DraftRecord = Record<string, unknown>;

/**
 * Read an event's stored drafts as a record of forms (anything else counts as no drafts).
 *
 * @param raw - The stored `draft:<id>` value.
 * @returns The record.
 */
export function asDraftRecord(raw: unknown): DraftRecord {
  return raw !== null && typeof raw === "object" && !Array.isArray(raw)
    ? { ...(raw as DraftRecord) }
    : {};
}

/** A form's draft: whether it has loaded, its stored values, and how to save or discard it. */
export interface FormDraft<T> {
  loaded: boolean;
  /** The stored values, or undefined if there are none. */
  draft: T | undefined;
  /** Save the form's values after the debounce (UISpec.md 6: about 500 ms). */
  save: (values: T) => void;
  /** Drop this form's draft, once its command has succeeded (UISpec.md 6, rule 8). */
  discard: () => Promise<void>;
  /**
   * Store a draft for another form of this event right away, unless it already has one (e.g. keep
   * Stage 2's archers when a changed Stage 1 clears them).
   */
  keep: (form: string, values: unknown) => Promise<void>;
}

/**
 * Keep one form's unsaved values in the event's draft, so a reload restores them. The forms of an
 * event share the `draft:<id>` value, one entry each; only one form is on screen at a time.
 *
 * @param eventId - The event id.
 * @param form - The form's entry name, e.g. "stage1".
 * @returns The draft state and actions.
 */
export function useFormDraft<T>(eventId: string, form: string): FormDraft<T> {
  const { store } = useServices();
  const [loaded, setLoaded] = useState<{ key: string; draft: T | undefined } | null>(null);
  const record = useRef<DraftRecord>({});
  const saver = useRef<DraftSaver | null>(null);
  const key = `${eventId}/${form}`;

  useEffect(() => {
    let cancelled = false;
    const own = new DraftSaver(store, eventId);
    saver.current = own;
    void getDraft(store, eventId).then((raw) => {
      if (cancelled) return;
      record.current = asDraftRecord(raw);
      setLoaded({ key, draft: record.current[form] as T | undefined });
    });
    return () => {
      cancelled = true;
      void own.flush();
    };
  }, [store, eventId, form, key]);

  const save = useCallback(
    (values: T) => {
      record.current = { ...record.current, [form]: values };
      saver.current?.schedule(record.current);
    },
    [form],
  );

  const discard = useCallback(async () => {
    saver.current?.cancel();
    const rest = { ...record.current };
    delete rest[form];
    record.current = rest;
    if (Object.keys(rest).length === 0) await deleteDraft(store, eventId);
    else await setDraft(store, eventId, rest);
  }, [store, eventId, form]);

  const keep = useCallback(
    async (other: string, values: unknown) => {
      if (other in record.current) return;
      record.current = { ...record.current, [other]: values };
      await setDraft(store, eventId, record.current);
    },
    [store, eventId],
  );

  const current = loaded !== null && loaded.key === key ? loaded : null;
  return { loaded: current !== null, draft: current?.draft, save, discard, keep };
}
