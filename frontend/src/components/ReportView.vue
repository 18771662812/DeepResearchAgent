<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { Source } from '../types'

const props = defineProps<{ markdown: string; sources: Source[] }>()

const CITATION_RE = /\[(\d+(?:\s*[,，]\s*\d+)*)\]/g

function escapeAttr(s: string) {
  return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')
}

// Markdown -> HTML -> 消毒 -> 把 [n] 替换为指向来源的上标链接
const html = computed(() => {
  const raw = marked.parse(props.markdown, { async: false }) as string
  const clean = DOMPurify.sanitize(raw)
  const byId = new Map(props.sources.map((s) => [s.id, s]))

  return clean.replace(CITATION_RE, (match, group: string) => {
    const ids = group.split(/\s*[,，]\s*/).map(Number)
    if (!ids.every((id) => byId.has(id))) return match
    const links = ids.map((id) => {
      const s = byId.get(id)!
      return `<a href="${escapeAttr(s.url)}" target="_blank" rel="noopener" title="${escapeAttr(s.title)}">${id}</a>`
    })
    return `<sup class="cite">[${links.join(', ')}]</sup>`
  })
})

function download() {
  const refs = props.sources.map((s) => `${s.id}. [${s.title}](${s.url})`).join('\n')
  const text = `${props.markdown}\n\n## 参考来源\n\n${refs}\n`
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = 'research-report.md'
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <article class="report panel">
    <div class="toolbar">
      <button @click="download">下载 Markdown</button>
    </div>
    <div class="markdown" v-html="html" />
    <section v-if="sources.length" class="sources">
      <h3>参考来源</h3>
      <ol>
        <li v-for="s in sources" :key="s.id" :value="s.id">
          <a :href="s.url" target="_blank" rel="noopener">{{ s.title || s.url }}</a>
          <div class="url">{{ s.url }}</div>
        </li>
      </ol>
    </section>
  </article>
</template>

<style scoped>
.report {
  padding: 24px 32px;
  min-width: 0;
}
.toolbar {
  display: flex;
  justify-content: flex-end;
}
.toolbar button {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--panel);
  color: var(--muted);
  font-size: 13px;
}
.toolbar button:hover {
  color: var(--accent);
  border-color: var(--accent);
}
.markdown {
  overflow-wrap: anywhere;
}
.markdown :deep(h1) {
  font-size: 1.6em;
  margin-top: 0;
}
.markdown :deep(h2) {
  font-size: 1.3em;
  margin-top: 1.6em;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border);
}
.markdown :deep(code) {
  padding: 1px 4px;
  border-radius: 4px;
  background: var(--code-bg);
  font-size: 0.9em;
}
.markdown :deep(pre) {
  padding: 12px;
  border-radius: 8px;
  background: var(--code-bg);
  overflow-x: auto;
}
.markdown :deep(pre code) {
  padding: 0;
}
.markdown :deep(blockquote) {
  margin: 0;
  padding-left: 12px;
  border-left: 3px solid var(--border);
  color: var(--muted);
}
.markdown :deep(table) {
  border-collapse: collapse;
  display: block;
  overflow-x: auto;
}
.markdown :deep(th),
.markdown :deep(td) {
  padding: 6px 12px;
  border: 1px solid var(--border);
}
.markdown :deep(.cite) {
  font-size: 0.75em;
}
.markdown :deep(.cite a) {
  text-decoration: none;
}
.sources {
  margin-top: 32px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
  font-size: 14px;
}
.sources h3 {
  margin-top: 0;
}
.sources li {
  margin-bottom: 8px;
}
.url {
  color: var(--muted);
  font-size: 12px;
  word-break: break-all;
}
@media (max-width: 640px) {
  .report {
    padding: 16px;
  }
}
</style>
