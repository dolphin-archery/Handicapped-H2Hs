import {
  Alert,
  Anchor,
  Button,
  Card,
  Group,
  Loader,
  NumberInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  useMatches,
} from "@mantine/core";
import { useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { useCurrentEvent } from "../app/currentEvent";
import { setupLocked, setupPath } from "../app/guards";
import { useServices } from "../app/services";
import { useFormDraft, type FormDraft } from "../app/useFormDraft";
import { CalculatorDrawer } from "../components/CalculatorForm";
import { EngineError } from "../engine/client";
import type {
  EventDocument,
  Options,
  Stage2Field,
  Stage2Info,
  Stage2Row,
  UpdatingForm,
} from "../engine/types";
import { useBridgeQuery } from "../engine/useBridgeQuery";
import { useEngineStatus } from "../engine/useEngineStatus";
import { drawSeed } from "./drawSeed";
import { SetupShell } from "./SetupShell";
import { stage2FromDocument, type Stage2Draft } from "./stage2Draft";

/** A rejected submit: the bridge message, and the row (0-based) and field it names. */
interface Stage2Error {
  message: string;
  row: number | null;
  field: Stage2Field | null;
}

const EMPTY_ROW: Stage2Row = { name: "", bowstyle: "", handicap: "" };

/**
 * The form's starting values: the draft, else the stored archers, else empty rows; always one row
 * per archer (Stage 1's count).
 *
 * @param doc - The event document.
 * @param draft - Stage 2's stored draft, if any.
 * @returns The rows and the updating parameters.
 */
function initialValues(doc: EventDocument, draft: Stage2Draft | undefined): Stage2Draft {
  const start = setupLocked(doc) ? stage2FromDocument(doc) : (draft ?? stage2FromDocument(doc));
  const rows = Array.from({ length: doc.setup.n_archers }, (_, i) => start.rows[i] ?? EMPTY_ROW);
  return { rows, updating: start.updating };
}

/**
 * `#/e/:id/setup/2`: the archers (UISpec.md 7.2 and 7.3, Stage 2). A table of rows on desktop and
 * one card per archer below `sm`; Advanced adds each archer's target and the handicap-updating
 * parameters. Values are kept as a draft while typing; Continue calls `apply_stage2`, stores the
 * document, then opens Stage 3. Read-only once the event has started.
 *
 * @param props.doc - The event document.
 * @returns The view.
 */
export function Stage2({ doc }: { doc: EventDocument }) {
  const draft = useFormDraft<Stage2Draft>(doc.id, "stage2");
  const options = useBridgeQuery("options", {});
  const info = useBridgeQuery("stage2_info", { doc });
  const failed = options.state === "error" ? options : info.state === "error" ? info : null;
  let body: ReactNode;
  if (failed !== null) {
    body = (
      <Alert color="red" title="Stage 2 cannot load">
        {failed.error.message}
      </Alert>
    );
  } else if (!draft.loaded || options.state !== "ok" || info.state !== "ok") {
    body = <Loader aria-label="Loading the form" />;
  } else {
    body = (
      <Stage2Form
        doc={doc}
        draft={draft}
        options={options.data}
        info={info.data}
        initial={initialValues(doc, draft.draft)}
      />
    );
  }
  return (
    <SetupShell doc={doc} stage={2} wide>
      {body}
    </SetupShell>
  );
}

/**
 * Stage 2's form once the draft, the option lists and the Stage 1 values have loaded.
 *
 * @param props.doc - The event document.
 * @param props.draft - The form's draft.
 * @param props.options - The bridge's option lists.
 * @param props.info - `stage2_info`: the shared target and the updating defaults.
 * @param props.initial - The values to start from.
 * @returns The form.
 */
function Stage2Form({
  doc,
  draft,
  options,
  info,
  initial,
}: {
  doc: EventDocument;
  draft: FormDraft<Stage2Draft>;
  options: Options;
  info: Stage2Info;
  initial: Stage2Draft;
}) {
  const { engine } = useServices();
  const { commit } = useCurrentEvent();
  const navigate = useNavigate();
  const engineStatus = useEngineStatus(engine);
  const [values, setValues] = useState(initial);
  const [error, setError] = useState<Stage2Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [calculatorOpen, setCalculatorOpen] = useState(false);
  const nameRefs = useRef<(HTMLInputElement | null)[]>([]);
  const cards = useMatches({ base: true, sm: false });
  const locked = setupLocked(doc);
  const advanced = info.setup_mode === "advanced";
  const { defaults } = options;
  const updating = values.updating;

  function store(next: Stage2Draft) {
    setValues(next);
    draft.save(next);
  }

  function changeRow(index: number, changes: Partial<Stage2Row>) {
    const rows = values.rows.map((row, i) => (i === index ? { ...row, ...changes } : row));
    store({ ...values, rows });
  }

  function changeUpdating(changes: Partial<UpdatingForm>) {
    store({ ...values, updating: { ...updating, ...changes } });
  }

  // Advanced fields left untouched take the Flask form's defaults; a cleared field is sent empty.
  const faceType = (row: Stage2Row) => row.face_type ?? defaults.face_type;
  const faceCm = (row: Stage2Row) => String(row.face_cm ?? defaults.face_cm);
  const distance = (row: Stage2Row) => row.distance ?? defaults.distance_key;
  const nLookback = updating.n_lookback ?? info.default_n_lookback;
  const startWeight = updating.start_weight ?? info.default_start_weight;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const archers = values.rows.map((row) => ({
      name: row.name,
      bowstyle: row.bowstyle,
      handicap: row.handicap,
      ...(advanced
        ? { distance: distance(row), face_cm: faceCm(row), face_type: faceType(row) }
        : {}),
    }));
    const updatingForm: UpdatingForm = advanced
      ? {
          update_handicaps: updating.update_handicaps,
          n_lookback: nLookback,
          start_weight: startWeight,
        }
      : { update_handicaps: false };
    try {
      const answer = await engine.call("apply_stage2", {
        doc,
        archers,
        updating: updatingForm,
        seed: drawSeed(),
      });
      if (!answer.ok) {
        setError({
          message: answer.error.message,
          row: answer.error.row ?? null,
          field: answer.error.field ?? null,
        });
        return;
      }
      if (!(await commit(answer.data.document))) return;
      await draft.discard();
      navigate(setupPath(doc.id, 3));
    } catch (caught) {
      const message = caught instanceof EngineError ? caught.message : String(caught);
      setError({ message, row: null, field: null });
    } finally {
      setBusy(false);
    }
  }

  const invalid = (row: number | null, field: Stage2Field) =>
    error !== null && error.row === row && error.field === field;
  const rowInvalid = (row: number) => error !== null && error.row === row;

  /** Enter in a name moves to the next row's name (the last row's Enter submits). */
  function nameKeyDown(index: number, event: KeyboardEvent<HTMLInputElement>) {
    const next = nameRefs.current[index + 1];
    if (event.key === "Enter" && next) {
      event.preventDefault();
      next.focus();
    }
  }

  /**
   * One archer's input for a field, labelled visibly in a card and by `aria-label` in the table
   * (whose header names the column).
   *
   * @param field - The field.
   * @param index - The row (0-based).
   * @returns The input.
   */
  function field(field: Stage2Field, index: number): ReactNode {
    const row = values.rows[index];
    const label = FIELD_LABELS[field];
    const labelProps = cards
      ? { label }
      : { "aria-label": `${label}, archer ${index + 1}`, miw: FIELD_WIDTHS[field] };
    const common = { ...labelProps, error: invalid(index, field), readOnly: locked };
    switch (field) {
      case "name":
        return (
          <TextInput
            {...common}
            ref={(el) => {
              nameRefs.current[index] = el;
            }}
            value={String(row.name)}
            onChange={(e) => changeRow(index, { name: e.currentTarget.value })}
            onKeyDown={(e) => nameKeyDown(index, e)}
            autoComplete="off"
          />
        );
      case "bowstyle":
        return (
          <Select
            {...common}
            placeholder="Choose..."
            data={options.bowstyles}
            value={row.bowstyle || null}
            onChange={(value) => changeRow(index, { bowstyle: value ?? "" })}
          />
        );
      case "handicap":
        return (
          <NumberInput
            {...common}
            inputMode="decimal"
            step={0.1}
            min={options.min_handicap}
            max={options.max_handicap}
            clampBehavior="none"
            hideControls
            value={row.handicap}
            onChange={(value) => changeRow(index, { handicap: value })}
          />
        );
      case "face_type":
        return (
          <Select
            {...common}
            data={options.face_types}
            value={faceType(row) || null}
            onChange={(value) => changeRow(index, { face_type: value ?? "" })}
          />
        );
      case "face_cm":
        return (
          <Select
            {...common}
            data={options.advanced_face_sizes.map((size) => ({
              value: String(size),
              label: `${size} cm`,
            }))}
            value={faceCm(row) || null}
            onChange={(value) => changeRow(index, { face_cm: value ?? "" })}
          />
        );
      default:
        return (
          <Select
            {...common}
            searchable
            data={options.distance_groups}
            value={distance(row) || null}
            onChange={(value) => changeRow(index, { distance: value ?? "" })}
          />
        );
    }
  }

  const fields: Stage2Field[] = advanced
    ? ["name", "bowstyle", "handicap", "face_type", "face_cm", "distance"]
    : ["name", "bowstyle", "handicap"];

  // The drawer stays outside the form: React events bubble through portals, so the calculator's
  // own submit would otherwise also submit Stage 2.
  return (
    <>
      <form onSubmit={(event) => void submit(event)}>
        <Stack>
          <Text size="sm">
            {advanced ? (
              <>
                Enter each of the {info.n_archers} archers, and the target face type, face size and
                distance each of them shoots. A distance of up to 25 m / 25 yd counts as indoor and
                anything further as outdoor. The face type is used exactly as chosen, so a Compound
                archer who should score only the inner ring as 10 needs a compound face type.
              </>
            ) : (
              <>
                Enter each of the {info.n_archers} archers. Everyone shoots{" "}
                {info.target.distance_label} with a face size of {info.target.face_cm} cm, which
                counts as {info.target.indoor ? "indoor" : "outdoor"}
                {info.target.indoor && ", so Compound archers score only the inner ring as 10"}.
              </>
            )}
          </Text>
          {!locked && (
            <Group>
              <Button variant="default" onClick={() => setCalculatorOpen(true)}>
                Handicap calculator
              </Button>
              <Text size="xs" c="dimmed">
                Need to work out a starting handicap? The calculator opens beside this form.
              </Text>
            </Group>
          )}
          <div aria-live="polite">
            {error !== null && (
              <Alert color="red" title="Please check the archers" data-testid="stage2-error">
                {error.message}
              </Alert>
            )}
          </div>

          {advanced && (
            <Stack gap="xs">
              <Text size="sm" fw={500} id="updating-label">
                Update handicaps during matches
              </Text>
              <Text size="xs" c="dimmed" id="updating-description">
                No: every archer&apos;s handicap stays as entered below for every pass. Yes: before
                each pass an archer&apos;s handicap is a weighted average of the one entered below
                and the handicap their recent shooting implies.
              </Text>
              <SegmentedControl
                aria-labelledby="updating-label"
                aria-describedby="updating-description"
                style={{ alignSelf: "flex-start" }}
                data={[
                  { value: "no", label: "No" },
                  { value: "yes", label: "Yes" },
                ]}
                value={updating.update_handicaps ? "yes" : "no"}
                onChange={(value) => changeUpdating({ update_handicaps: value === "yes" })}
                readOnly={locked}
                data-testid="update-handicaps"
              />
              {updating.update_handicaps && (
                <SimpleGrid cols={{ base: 1, sm: 2 }} maw={760}>
                  <NumberInput
                    label="Lookback (passes)"
                    description="How many of an archer's latest passes their recent shooting is taken from; 1 uses only the previous pass."
                    inputMode="numeric"
                    allowDecimal={false}
                    min={1}
                    clampBehavior="none"
                    value={nLookback}
                    onChange={(value) => changeUpdating({ n_lookback: value })}
                    error={invalid(null, "n_lookback")}
                    readOnly={locked}
                  />
                  <NumberInput
                    label="Start weight (passes)"
                    description="How many passes' worth of arrows the entered handicap counts for."
                    inputMode="numeric"
                    allowDecimal={false}
                    min={1}
                    clampBehavior="none"
                    value={startWeight}
                    onChange={(value) => changeUpdating({ start_weight: value })}
                    error={invalid(null, "start_weight")}
                    readOnly={locked}
                  />
                </SimpleGrid>
              )}
            </Stack>
          )}

          {cards ? (
            <Stack data-testid="archer-cards">
              {values.rows.map((_, index) => (
                <Card
                  key={index}
                  withBorder
                  padding="sm"
                  data-invalid={rowInvalid(index) || undefined}
                  style={rowInvalid(index) ? INVALID_STYLE : undefined}
                >
                  <Text fw={600} size="sm" mb="xs">
                    Archer {index + 1}
                  </Text>
                  <Stack gap="xs">
                    {fields.map((f) => (
                      <div key={f}>{field(f, index)}</div>
                    ))}
                  </Stack>
                </Card>
              ))}
            </Stack>
          ) : (
            <Table.ScrollContainer minWidth={advanced ? 1000 : 560}>
              <Table data-testid="archer-table" verticalSpacing="xs">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w={40}>#</Table.Th>
                    {fields.map((f) => (
                      <Table.Th key={f}>{FIELD_LABELS[f]}</Table.Th>
                    ))}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {values.rows.map((_, index) => (
                    <Table.Tr
                      key={index}
                      data-invalid={rowInvalid(index) || undefined}
                      style={rowInvalid(index) ? INVALID_STYLE : undefined}
                    >
                      <Table.Td>{index + 1}</Table.Td>
                      {fields.map((f) => (
                        <Table.Td key={f}>{field(f, index)}</Table.Td>
                      ))}
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}

          <Group>
            <Anchor component={Link} to={setupPath(doc.id, 1)} size="sm">
              Back to Stage 1
            </Anchor>
            {!locked && (
              <Button
                type="submit"
                loading={busy || engineStatus.state === "loading"}
                disabled={engineStatus.state === "failed"}
              >
                Continue
              </Button>
            )}
          </Group>
        </Stack>
      </form>
      <CalculatorDrawer opened={calculatorOpen} onClose={() => setCalculatorOpen(false)} />
    </>
  );
}

const FIELD_LABELS: Record<Stage2Field, string> = {
  name: "Name",
  bowstyle: "Bowstyle",
  handicap: "Handicap",
  face_type: "Face type",
  face_cm: "Face size",
  distance: "Distance",
  n_lookback: "Lookback",
  start_weight: "Start weight",
};

/** Minimum widths of the table's inputs, so long option labels stay readable. */
const FIELD_WIDTHS: Partial<Record<Stage2Field, number>> = {
  name: 160,
  bowstyle: 130,
  handicap: 90,
  face_type: 240,
  face_cm: 100,
  distance: 110,
};

/** The offending row's highlight: the theme's light red, plus a red outline. */
const INVALID_STYLE = {
  backgroundColor: "var(--mantine-color-red-light)",
  outline: "2px solid var(--mantine-color-red-filled)",
  outlineOffset: -2,
};
