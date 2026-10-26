/** A proxy address fit for the screen: the password in scheme://user:pass@host becomes ***. */
export function maskProxy(proxy: string): string {
  return proxy.replace(/(:\/\/[^:/@]*):[^@/]*@/, "$1:***@");
}
