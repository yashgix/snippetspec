export const UNKNOWN = Symbol("UNKNOWN")
export type Value = null | boolean | number | string | typeof UNKNOWN | Value[] | { [key: string]: Value }
export type Obj = Record<string, unknown>

export function isObject(value: unknown): value is Obj {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

export function containsUnknown(value: Value): boolean {
  if (value === UNKNOWN) return true
  if (Array.isArray(value)) return value.some(containsUnknown)
  return isObject(value) && Object.values(value).some((item) => containsUnknown(item as Value))
}

export function truthy(value: Value): boolean {
  if (Array.isArray(value)) return value.length > 0
  if (isObject(value)) return Object.keys(value).length > 0
  return Boolean(value)
}
