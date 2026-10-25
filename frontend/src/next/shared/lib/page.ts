/** Full-page navigation, behind an object so tests can replace it (jsdom cannot navigate or reload). */
export const page = {
  assign: (url: string) => window.location.assign(url),
  reload: () => window.location.reload(),
};
