/**
 * The event routes (UISpec.md 7.1): the layout that loads the event in the URL (or shows "Event
 * not found"), the guard wrapper, and the views.
 */
import { Alert, Anchor, Button, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useEffect, type ReactNode } from "react";
import { Link, Navigate, Outlet, useNavigate, useParams } from "react-router";
import { useCurrentEvent } from "../app/currentEvent";
import { eventHomePath, guardEventView, type EventView, type ResultTab } from "../app/guards";
import { useServices } from "../app/services";
import { confirmDelete, downloadBackup } from "../components/eventActions";
import type { EventDocument } from "../engine/types";
import { Stage1 } from "../setup/Stage1";
import { Stage2 } from "../setup/Stage2";
import { Stage3 } from "../setup/Stage3";
import { ResultsView } from "../results/Results";
import { MatchPage } from "../scoring/MatchPage";
import { PassOverview } from "../scoring/PassOverview";

/**
 * Layout for `#/e/:id/...`: waits for the stored event, then shows the view; an unknown id gives
 * "Event not found" with a link Home; an unreadable stored value offers export, then delete.
 *
 * @returns The layout element.
 */
export function EventLayout() {
  const { state, routeId, remove } = useCurrentEvent();
  const { store } = useServices();
  const navigate = useNavigate();
  if (state.kind === "found" && state.id === routeId) return <Outlet />;
  if (state.kind === "missing" && state.id === routeId) {
    return (
      <Stack>
        <Title order={1}>Event not found</Title>
        <Text>There is no saved event at this address in this browser.</Text>
        <Anchor component={Link} to="/">
          Go to Home
        </Anchor>
      </Stack>
    );
  }
  if (state.kind === "corrupt" && state.id === routeId) {
    return (
      <Alert color="red" title="This saved event cannot be read">
        <Text size="sm">Download what can be read, then delete it.</Text>
        <Group mt="sm">
          <Button size="xs" variant="default" onClick={() => void downloadBackup(store, state.raw)}>
            Download what can be read
          </Button>
          <Button
            size="xs"
            color="red"
            onClick={() =>
              confirmDelete("this event", () => void remove().then(() => navigate("/")))
            }
          >
            Delete
          </Button>
        </Group>
      </Alert>
    );
  }
  if (state.kind === "failed" && state.id === routeId) {
    return (
      <Alert color="red" title="The event cannot be read">
        {state.message}
      </Alert>
    );
  }
  return <Loader aria-label="Loading the event" />;
}

/** Opens `#/e/:id` at the event's remembered or default view. */
export function EventIndex() {
  const { state } = useCurrentEvent();
  return state.kind === "found" ? <Navigate to={eventHomePath(state.doc)} replace /> : null;
}

/**
 * Show a view only if the stored event allows it; otherwise redirect with a short notification
 * (UISpec.md 6, rule 5).
 *
 * @param props.view - The view the route asks for.
 * @param props.children - The view.
 * @returns The view, or a redirect.
 */
function Guarded({ view, children }: { view: EventView; children: ReactNode }) {
  const { state } = useCurrentEvent();
  const verdict =
    state.kind === "found" ? guardEventView(state.doc, view) : { allowed: true as const };
  const message = verdict.allowed ? "" : verdict.message;
  useEffect(() => {
    if (message) notifications.show({ message });
  }, [message]);
  if (!verdict.allowed) return <Navigate to={verdict.redirect} replace />;
  return <>{children}</>;
}

/**
 * Render a view with the loaded event document (EventLayout shows the view only once it is found).
 *
 * @param props.children - Renders the view from the document.
 * @returns The view, or nothing while the event is not loaded.
 */
function WithDocument({ children }: { children: (doc: EventDocument) => ReactNode }) {
  const { state } = useCurrentEvent();
  return state.kind === "found" ? <>{children(state.doc)}</> : null;
}

/** `#/e/:id/setup/:stage`. */
export function SetupRoute() {
  const stage = Number(useParams().stage);
  if (stage !== 1 && stage !== 2 && stage !== 3) return <Navigate to=".." replace />;
  const View = { 1: Stage1, 2: Stage2, 3: Stage3 }[stage];
  return (
    <Guarded view={{ kind: "setup", stage }}>
      <WithDocument>{(doc) => <View doc={doc} />}</WithDocument>
    </Guarded>
  );
}

/** `#/e/:id/pass`. */
export function PassRoute() {
  return (
    <Guarded view={{ kind: "pass" }}>
      <WithDocument>{(doc) => <PassOverview doc={doc} />}</WithDocument>
    </Guarded>
  );
}

/** `#/e/:id/pass/match/:i`. */
export function MatchRoute() {
  const index = useParams().i ?? "";
  return (
    <Guarded view={{ kind: "match", index }}>
      <WithDocument>{(doc) => <MatchPage doc={doc} index={Number(index)} />}</WithDocument>
    </Guarded>
  );
}

/** `#/e/:id/results/:tab`. */
export function ResultsRoute() {
  const tab = useParams().tab ?? "";
  return (
    <Guarded view={{ kind: "results", tab }}>
      <WithDocument>{(doc) => <ResultsView doc={doc} tab={tab as ResultTab} />}</WithDocument>
    </Guarded>
  );
}
