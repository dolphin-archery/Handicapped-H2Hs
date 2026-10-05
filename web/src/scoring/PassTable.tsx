import { Table } from "@mantine/core";
import type { PassTableRow } from "../engine/types";

/** The thick line between matches, so it is clear who was paired with whom (UISpec.md 7.3). */
const MATCH_SEPARATOR = { borderTop: "3px double var(--mantine-color-default-border)" };

/**
 * A pass results table (the Flask `_pass_table.html`): one group of rows per match, separated by
 * a thick line; "Pass starting handicap" only when handicaps are updated. Values are the bridge's
 * text, shown as they are.
 *
 * @param props.groups - One list of rows per match.
 * @param props.showStartHandicap - Whether to show the "Pass starting handicap" column.
 * @returns The table.
 */
export function PassTable({
  groups,
  showStartHandicap,
}: {
  groups: PassTableRow[][];
  showStartHandicap: boolean;
}) {
  return (
    <Table.ScrollContainer minWidth={300}>
      <Table data-testid="pass-table" verticalSpacing="xs" horizontalSpacing="xs">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Archer</Table.Th>
            <Table.Th>Score</Table.Th>
            <Table.Th>Percentile</Table.Th>
            {showStartHandicap && <Table.Th>Pass starting handicap</Table.Th>}
            <Table.Th>Handicap</Table.Th>
            <Table.Th>Winner</Table.Th>
          </Table.Tr>
        </Table.Thead>
        {groups.map((rows, g) => (
          <Table.Tbody key={g} style={g > 0 ? MATCH_SEPARATOR : undefined}>
            {rows.map((row, r) => (
              <Table.Tr key={r}>
                <Table.Td>{row.archer}</Table.Td>
                <Table.Td>{row.score}</Table.Td>
                <Table.Td>{row.percentile}</Table.Td>
                {showStartHandicap && <Table.Td>{row.start_handicap}</Table.Td>}
                <Table.Td>{row.handicap}</Table.Td>
                <Table.Td>{row.winner}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        ))}
      </Table>
    </Table.ScrollContainer>
  );
}
