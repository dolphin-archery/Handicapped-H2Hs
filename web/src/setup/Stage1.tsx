import {
  Alert,
  Button,
  Group,
  Loader,
  NumberInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Slider,
  Stack,
  Text,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { useCurrentEvent } from "../app/currentEvent";
import { setupLocked, setupPath } from "../app/guards";
import { useServices } from "../app/services";
import { useFormDraft, type FormDraft } from "../app/useFormDraft";
import { EngineError } from "../engine/client";
import type { EventDocument, Options, SetupMode, Stage1Form } from "../engine/types";
import { useBridgeQuery, type Query } from "../engine/useBridgeQuery";
import { useEngineStatus } from "../engine/useEngineStatus";
import { byesApply, snapToDivisor } from "./divisors";
import { SetupShell } from "./SetupShell";
import { stage2FromDocument } from "./stage2Draft";

/** Stage 1's values as typed (also its draft). */
export interface Stage1Values {
  n_archers: string | number;
  total_arrows: string | number;
  /** The arrows per pass the user last chose; the control shows the nearest divisor. */
  preferred_n_pass: number;
  setup_mode: SetupMode;
  shoot_byes: boolean;
  distance: string;
  face_cm: string;
}

/**
 * Stage 1's values as stored in the document (the defaults for a new event).
 *
 * @param doc - The event document.
 * @returns The values.
 */
function fromDocument(doc: EventDocument): Stage1Values {
  const { setup } = doc;
  return {
    n_archers: setup.n_archers,
    total_arrows: setup.total_arrows,
    preferred_n_pass: setup.n_pass,
    setup_mode: setup.setup_mode,
    shoot_byes: setup.shoot_byes,
    distance: setup.target.distance_key,
    face_cm: String(setup.target.face_cm),
  };
}

/**
 * The `apply_stage1` form for the values (n_pass is the divisor the control shows).
 *
 * @param values - The typed values.
 * @returns The bridge form.
 */
function toForm(values: Stage1Values): Stage1Form {
  const { options, index } = snapToDivisor(values.total_arrows, values.preferred_n_pass);
  return {
    n_archers: values.n_archers,
    total_arrows: values.total_arrows,
    n_pass: options[index],
    setup_mode: values.setup_mode,
    shoot_byes: values.shoot_byes,
    ...(values.setup_mode === "simple"
      ? { distance: values.distance, face_cm: values.face_cm }
      : {}),
  };
}

/**
 * Whether submitting would store exactly what is already stored, so Continue can move on without
 * `apply_stage1` (which clears Stages 2 and 3).
 *
 * @param doc - The event document.
 * @param form - The bridge form about to be sent.
 * @returns True if Stage 1 is done and nothing it stores would change.
 */
function unchanged(doc: EventDocument, form: Stage1Form): boolean {
  const { setup } = doc;
  const sameTarget =
    form.setup_mode === "advanced" ||
    (form.distance === setup.target.distance_key && Number(form.face_cm) === setup.target.face_cm);
  return (
    setup.stage >= 1 &&
    String(form.n_archers) === String(setup.n_archers) &&
    String(form.total_arrows) === String(setup.total_arrows) &&
    form.n_pass === setup.n_pass &&
    form.setup_mode === setup.setup_mode &&
    form.shoot_byes === setup.shoot_byes &&
    sameTarget
  );
}

/**
 * `#/e/:id/setup/1`: the event as a whole (UISpec.md 7.2 and 7.3, Stage 1). Values are kept as a
 * draft while typing; Continue calls `apply_stage1`, stores the document, then opens Stage 2.
 * Read-only once the event has started.
 *
 * @param props.doc - The event document.
 * @returns The view.
 */
export function Stage1({ doc }: { doc: EventDocument }) {
  const draft = useFormDraft<Stage1Values>(doc.id, "stage1");
  const options = useBridgeQuery("options", {});
  return (
    <SetupShell doc={doc} stage={1}>
      {draft.loaded ? (
        <Stage1Fields
          doc={doc}
          draft={draft}
          initial={setupLocked(doc) ? fromDocument(doc) : (draft.draft ?? fromDocument(doc))}
          options={options}
        />
      ) : (
        <Loader role="status" aria-label="Loading the form" />
      )}
    </SetupShell>
  );
}

/**
 * Stage 1's fields once the draft has loaded.
 *
 * @param props.doc - The event document.
 * @param props.draft - The form's draft.
 * @param props.initial - The values to start from (the draft, else the document's).
 * @param props.options - The bridge's option lists (distances, face sizes), perhaps still loading.
 * @returns The form.
 */
function Stage1Fields({
  doc,
  draft,
  initial,
  options,
}: {
  doc: EventDocument;
  draft: FormDraft<Stage1Values>;
  initial: Stage1Values;
  options: Query<Options>;
}) {
  const { engine } = useServices();
  const { commit } = useCurrentEvent();
  const navigate = useNavigate();
  const engineStatus = useEngineStatus(engine);
  const [values, setValues] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const locked = setupLocked(doc);
  const { options: divisorList, index } = snapToDivisor(
    values.total_arrows,
    values.preferred_n_pass,
  );
  const lists = options.state === "ok" ? options.data : null;

  function change(next: Partial<Stage1Values>) {
    const merged = { ...values, ...next };
    setValues(merged);
    draft.save(merged);
  }

  async function submit(form: Stage1Form) {
    setBusy(true);
    setError(null);
    try {
      const answer = await engine.call("apply_stage1", { doc, form });
      if (!answer.ok) {
        setError(answer.error.message);
        return;
      }
      // apply_stage1 clears the archers: keep them as Stage 2's draft so nothing typed is lost.
      if (doc.archers.length > 0) await draft.keep("stage2", stage2FromDocument(doc));
      if (!(await commit(answer.data.document))) return;
      await draft.discard();
      navigate(setupPath(doc.id, 2));
    } catch (caught) {
      setError(caught instanceof EngineError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const form = toForm(values);
    if (unchanged(doc, form)) {
      void draft.discard().then(() => navigate(setupPath(doc.id, 2)));
      return;
    }
    if (doc.setup.stage >= 2) {
      modals.openConfirmModal({
        title: "Change the event setup?",
        children: (
          <Text size="sm">
            Changing Stage 1 clears the pairings and the archers saved in Stage 2. The archers typed
            so far are kept on the Stage 2 form to submit again.
          </Text>
        ),
        labels: { confirm: "Change setup", cancel: "Keep the current setup" },
        onConfirm: () => void submit(form),
      });
      return;
    }
    void submit(form);
  }

  return (
    <form onSubmit={onSubmit}>
      <Stack>
        <Text size="sm" c="dimmed">
          Set up the event as a whole. Archer names, bowstyles and handicaps are entered next, in
          Stage 2.
        </Text>
        <div aria-live="polite">
          {error !== null && (
            <Alert color="red" title="Please check the setup" data-testid="stage1-error">
              {error}
            </Alert>
          )}
        </div>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <NumberInput
            label="Number of archers"
            inputMode="numeric"
            allowDecimal={false}
            min={2}
            clampBehavior="none"
            value={values.n_archers}
            onChange={(value) => change({ n_archers: value })}
            readOnly={locked}
          />
          <NumberInput
            label="Total arrows"
            inputMode="numeric"
            allowDecimal={false}
            min={1}
            clampBehavior="none"
            value={values.total_arrows}
            onChange={(value) => change({ total_arrows: value })}
            readOnly={locked}
          />
        </SimpleGrid>

        <div>
          <Text size="sm" fw={500} id="n-pass-label">
            Arrows per pass:{" "}
            <Text span fw={700} data-testid="n-pass-value">
              {divisorList[index]}
            </Text>
          </Text>
          <Text size="xs" c="dimmed" mb="xs">
            Only numbers that divide the total arrows are offered.
          </Text>
          <Slider
            aria-labelledby="n-pass-label"
            min={0}
            max={Math.max(divisorList.length - 1, 0)}
            step={1}
            value={index}
            onChange={(i) => change({ preferred_n_pass: divisorList[i] })}
            label={(i) => divisorList[i]}
            marks={divisorList.map((value, i) => ({
              value: i,
              label:
                i === 0 || i === divisorList.length - 1 || divisorList.length <= 12
                  ? String(value)
                  : undefined,
            }))}
            disabled={locked}
            mb="lg"
            thumbLabel="Arrows per pass"
            thumbProps={{ "aria-valuetext": String(divisorList[index]) }}
          />
        </div>

        {byesApply(values.n_archers) && (
          <div>
            <Text size="sm" fw={500} id="byes-label">
              Shoot byes?
            </Text>
            <Text size="xs" c="dimmed" mb="xs" id="byes-description">
              With an odd number of archers, one archer has no opponent each pass. Yes: they still
              shoot, on their own, so every archer shoots every pass. No: they sit that pass out,
              which adds passes to the event so that everyone still shoots all of their arrows.
            </Text>
            <SegmentedControl
              aria-labelledby="byes-label"
              aria-describedby="byes-description"
              data={[
                { value: "yes", label: "Yes" },
                { value: "no", label: "No" },
              ]}
              value={values.shoot_byes ? "yes" : "no"}
              onChange={(value) => change({ shoot_byes: value === "yes" })}
              readOnly={locked}
              data-testid="shoot-byes"
            />
          </div>
        )}

        <div>
          <Text size="sm" fw={500} id="setup-mode-label" mb={4}>
            Setup mode
          </Text>
          <SegmentedControl
            aria-labelledby="setup-mode-label"
            data={[
              { value: "simple", label: "Simple" },
              { value: "advanced", label: "Advanced" },
            ]}
            value={values.setup_mode}
            onChange={(value) => change({ setup_mode: value as SetupMode })}
            readOnly={locked}
          />
        </div>

        {values.setup_mode === "simple" ? (
          <>
            <Text size="xs" c="dimmed">
              Simple setup: every archer shoots the same distance at the same target face size (the
              standard single-face target, not 3-spot). Distances up to 25 m / 25 yd count as indoor
              (indoor arrow size, and Compound archers score only the inner ring as 10); longer
              distances count as outdoor.
            </Text>
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <Select
                label="Distance"
                searchable
                allowDeselect={false}
                data={lists?.distance_groups ?? []}
                value={lists === null ? null : values.distance}
                placeholder={lists === null ? "Loading..." : undefined}
                onChange={(value) => value !== null && change({ distance: value })}
                readOnly={locked}
                disabled={lists === null}
              />
              <Select
                label="Face size"
                allowDeselect={false}
                data={(lists?.face_sizes ?? []).map((size) => ({
                  value: String(size),
                  label: `${size} cm`,
                }))}
                value={lists === null ? null : values.face_cm}
                placeholder={lists === null ? "Loading..." : undefined}
                onChange={(value) => value !== null && change({ face_cm: value })}
                readOnly={locked}
                disabled={lists === null}
              />
            </SimpleGrid>
          </>
        ) : (
          <Text size="sm" data-testid="advanced-note">
            Advanced setup: each archer shoots their own target face type, face size and distance.
            You choose them for every archer in Stage 2.
          </Text>
        )}

        {!locked && (
          <Group>
            <Button
              type="submit"
              loading={busy || engineStatus.state === "loading"}
              disabled={engineStatus.state === "failed"}
            >
              Continue
            </Button>
          </Group>
        )}
      </Stack>
    </form>
  );
}
