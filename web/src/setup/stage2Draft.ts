import type { EventDocument, Stage2Row, UpdatingForm } from "../engine/types";

/** Stage 2's draft: the archer rows and the updating parameters, as typed. */
export interface Stage2Draft {
  rows: Stage2Row[];
  updating: UpdatingForm;
}

/**
 * Stage 2's values as stored in the document, in the form's shape (to start the form, or to keep
 * the archers as a draft when a changed Stage 1 clears them).
 *
 * @param doc - The event document.
 * @returns The rows (entry order) and the updating parameters.
 */
export function stage2FromDocument(doc: EventDocument): Stage2Draft {
  const { setup } = doc;
  return {
    rows: doc.archers.map((archer) => ({
      name: archer.name,
      bowstyle: archer.bowstyle,
      handicap: archer.handicap,
      ...(archer.target === null
        ? {}
        : {
            distance: archer.target.distance_key,
            face_cm: archer.target.face_cm,
            face_type: archer.target.face_type,
          }),
    })),
    updating: {
      update_handicaps: setup.update_handicaps,
      ...(setup.n_lookback === null ? {} : { n_lookback: setup.n_lookback }),
      ...(setup.start_weight === null ? {} : { start_weight: setup.start_weight }),
    },
  };
}
