/** 백엔드 호출은 여기 한 곳에서만 한다. 토큰과 오류 응답({error, message})을 다룬다. */

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

let token: string | null = null

export function setToken(value: string | null) {
  token = value
}

export class ApiError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

interface RequestOptions {
  method?: string
  json?: unknown
  form?: FormData
}

export async function request<T>(
  path: string,
  { method, json, form }: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  let body: BodyInit | undefined = form
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(json)
  }
  let response: Response
  try {
    response = await fetch(API_BASE + path, {
      method: method ?? (body ? 'POST' : 'GET'),
      headers,
      body,
    })
  } catch {
    throw new ApiError(0, 'NETWORK', '서버에 연결할 수 없어요. 백엔드가 켜져 있는지 확인해 주세요')
  }
  const data = parse(await response.text())
  if (!response.ok) {
    throw new ApiError(
      response.status,
      data?.error ?? 'HTTP',
      data?.message ?? `요청이 실패했어요 (${response.status})`,
    )
  }
  return data as T
}

function parse(text: string) {
  try {
    return text ? JSON.parse(text) : null
  } catch {
    return null
  }
}
