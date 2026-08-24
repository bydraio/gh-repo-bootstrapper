## Next.js/browser-capable projects

When the repository already has a browser capture capability, use that
capability against local or fictional fixture data and follow its existing
setup instructions. Do not assume a particular browser tool, command, route,
or dependency: this template does not create any of them.

For a macOS project that uses `next dev`, the application documentation should
tell local operators to prefix the development command with `ulimit -n 10240 &&`
in the same shell. This is a temporary per-shell workaround that helps avoid
Watchpack `EMFILE` failures, not a shell-profile or persistent system setting.
Keep any browser-test port, server-lifecycle, and serial-execution guidance
specific to the generated application.

Review the rendered result for layout, content, and sensitive-data boundaries
before adding an image to version control. Keep any accepted capture workflow
and repository-specific selectors in the application repository.
