import { ActionIcon, Menu, useMantineColorScheme, type MantineColorScheme } from "@mantine/core";
import { AutoIcon, MoonIcon, SunIcon } from "./icons";

const CHOICES: { value: MantineColorScheme; label: string; icon: () => React.JSX.Element }[] = [
  { value: "light", label: "Light", icon: SunIcon },
  { value: "dark", label: "Dark", icon: MoonIcon },
  { value: "auto", label: "Automatic (follow the device)", icon: AutoIcon },
];

/**
 * The colour scheme choice: light, dark or automatic (decision D8). The choice is a device
 * setting, stored through the settings colour-scheme manager.
 *
 * @returns A header icon button with a menu.
 */
export function ColorSchemeMenu() {
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const Current = CHOICES.find((c) => c.value === colorScheme)?.icon ?? AutoIcon;
  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <ActionIcon variant="default" size="lg" aria-label="Colour scheme">
          <Current />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Colour scheme</Menu.Label>
        {CHOICES.map(({ value, label, icon: Icon }) => (
          <Menu.Item
            key={value}
            leftSection={<Icon />}
            onClick={() => setColorScheme(value)}
            aria-current={colorScheme === value ? "true" : undefined}
            fw={colorScheme === value ? 700 : undefined}
          >
            {label}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}
