import type { RequestHandler } from 'msw'

// API 핸들러는 4단계(API 함수 + mock 서버)에서 채운다
export const handlers: RequestHandler[] = []
