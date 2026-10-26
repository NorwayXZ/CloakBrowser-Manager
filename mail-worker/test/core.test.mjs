import assert from "node:assert/strict";
import test from "node:test";
import { clip, isAuthorized, normalizeAddress, parseLimit, retentionCutoff, secretsEqual } from "../src/core.ts";

test("normalizeAddress accepts only well-formed addresses on the domain", () => {
  assert.equal(normalizeAddress("  Nina.Shaw42@Example.com ", "example.com"), "nina.shaw42@example.com");
  for (const bad of ["x@other.com", "x@sub.example.com", "@example.com", "a b@example.com", "x@example.com\r\nBcc: y@z.com", "", null, 42, "x@example.com.evil.io"]) {
    assert.equal(normalizeAddress(bad, "example.com"), null, String(bad));
  }
});

test("isAuthorized needs the exact bearer token and refuses an unset one", () => {
  assert.equal(isAuthorized("Bearer s3cret", "s3cret"), true);
  assert.equal(isAuthorized("Bearer s3cret ", "s3cret"), false);
  assert.equal(isAuthorized("Bearer wrong", "s3cret"), false);
  assert.equal(isAuthorized("s3cret", "s3cret"), false);
  assert.equal(isAuthorized(null, "s3cret"), false);
  assert.equal(isAuthorized("Bearer ", ""), false);
  assert.equal(isAuthorized("Bearer x", undefined), false);
});

test("secretsEqual", () => {
  assert.equal(secretsEqual("abc", "abc"), true);
  assert.equal(secretsEqual("abc", "abd"), false);
  assert.equal(secretsEqual("abc", "abcd"), false);
});

test("clip, parseLimit, retentionCutoff", () => {
  assert.equal(clip("abcdef", 3), "abc");
  assert.equal(clip(null, 3), null);
  assert.equal(parseLimit("500", 50, 100), 100);
  assert.equal(parseLimit("x", 50, 100), 50);
  assert.equal(parseLimit("0", 50, 100), 50);
  assert.equal(retentionCutoff(new Date("2026-10-26T00:00:00Z"), 7), "2026-10-19T00:00:00.000Z");
});
