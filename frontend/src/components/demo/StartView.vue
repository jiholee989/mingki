<script setup lang="ts">
import { demoRegulation } from '@/api/tasks'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, withSubject } from '@/lib/briefing'

defineProps<{ busy: boolean }>()
const emit = defineEmits<{ start: [] }>()

const { title, oldVersion, newVersion, effectiveFrom } = demoRegulation
</script>

<template>
  <section class="pt-20">
    <p class="text-muted-foreground">
      {{ oldVersion }} → {{ newVersion }} · {{ formatDate(effectiveFrom) }} 시행
    </p>
    <h1 class="mt-2 text-3xl leading-snug font-bold">{{ withSubject(title) }}<br />바뀌었어요</h1>
    <Button
      size="lg"
      class="mt-10 h-14 w-full rounded-xl text-base"
      :disabled="busy"
      @click="emit('start')"
    >
      <Spinner v-if="busy" />
      영향받는 상품 찾기
    </Button>
  </section>
</template>
