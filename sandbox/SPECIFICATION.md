# Sandbox App Specification

## 1. Overview
The Sandbox App is a minimal GUI module used to verify window creation and embedding behavior in the CAD_Generators workspace.

It supports two launch modes:
- Standalone window mode (own root window and event loop)
- Embedded toplevel mode (child window under an existing parent)

## 2. Goals
- Provide a simple visual test surface for UI integration.
- Demonstrate launching from the main menu and from direct execution.
- Keep implementation intentionally small and easy to refactor.

## 3. Out of Scope
- Data input or persistence
- CAD generation or file export
- Complex layout or theming controls

## 4. Runtime Behavior
### 4.1 Standalone Launch
When launched directly (via `main()`):
- Create a `ttkbootstrap.Window` with theme `darkly`.
- Set title to `Sandbox App`.
- Set geometry to `300x100`.
- Render a single centered label reading `Hello World!` with font `Segoe UI, 16, bold`.
- Start the Tk event loop.

### 4.2 Embedded Launch
When launched with a parent (`tk.Misc`):
- Create a `tk.Toplevel` child of the supplied parent.
- Apply the same UI settings as standalone mode.
- Do not start a new event loop.

## 5. Public API
The module exposes:
- `launch_in_toplevel(parent: tk.Misc) -> None`
  - Creates a `tk.Toplevel` child window under the provided parent.
  - Applies the shared Sandbox UI.
  - Does not start a new event loop.
- `main() -> None`
  - Creates a standalone themed root window.
  - Applies the shared Sandbox UI.
  - Starts the Tk event loop.

## 6. Internal Structure
- `_build_ui(window: tk.Toplevel | ttk.Window) -> None`
  - Applies shared title, geometry, and label creation.
  - Avoids duplicate UI code between launch paths.

## 7. Integration Requirements
- Must be importable by the main menu launcher.
- Must preserve script entry-point compatibility via `main()`.
- Must run without wildcard imports.

## 8. Acceptance Criteria
- Running the module directly opens a 300x100 themed window with `Hello World!`.
- Calling `launch_in_toplevel(existing_parent)` opens a child window under that parent.
- No Pylance warnings in the module.
- Main menu can launch the sandbox window successfully.

## 9. Future Enhancements (Optional)
- Add configurable title and message text.
- Add basic close/callback hooks for integration tests.
- Add lightweight UI controls for sandbox experimentation.
