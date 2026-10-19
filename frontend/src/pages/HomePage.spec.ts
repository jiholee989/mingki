import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import HomePage from './HomePage.vue'

describe('HomePage', () => {
  it('제목을 표시한다', () => {
    const wrapper = mount(HomePage)
    expect(wrapper.text()).toContain('Rule Ripple')
  })
})
