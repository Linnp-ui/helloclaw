<script setup lang="ts">
import { ref, watch, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { Input, Button, message, Tag } from 'ant-design-vue'
import { SendOutlined, PlusOutlined, StopOutlined, LoadingOutlined, AudioOutlined, AudioFilled } from '@ant-design/icons-vue'
import { useRouter, useRoute } from 'vue-router'
import { sessionApi } from '@/api/session'
import { chatApi } from '@/api/chat'
import { configApi } from '@/api/config'
import { renderMarkdown, formatTime } from '@/utils/markdown'
import { getToolConfig, formatToolArgs, formatToolResult } from '@/utils/toolDisplay'
import LobsterIcon from '@/assets/lobster.svg'

// localStorage key for saving current session
const SESSION_STORAGE_KEY = 'helloclaw.lastSessionId'

// 助手名字（从后端获取）
const assistantName = ref('HelloClaw')

// 消息段类型
interface TextSegment {
  type: 'text'
  id: number
  content: string
}

interface ToolSegment {
  type: 'tool'
  id: number
  tool: string
  args: Record<string, unknown>
  result?: string
  status: 'running' | 'done' | 'error'
}

type MessageSegment = TextSegment | ToolSegment

interface Message {
  id: number
  role: 'user' | 'assistant'
  content: string  // 用于从历史加载的消息
  timestamp: Date
  segments?: MessageSegment[]  // 用于流式消息的分段
  images?: string[]  // 用户消息中的图片
}

interface MessageGroup {
  role: 'user' | 'assistant'
  messages: Message[]
}

const router = useRouter()
const route = useRoute()
const inputMessage = ref('')
const messages = ref<Message[]>([])
const loading = ref(false)
const currentSessionId = ref<string | null>(null)
const messagesContainer = ref<HTMLElement | null>(null)
const abortController = ref<AbortController | null>(null)
const initializing = ref(true)
const collapsedTools = ref<Set<number>>(new Set())
// 默认所有工具都是展开的（用于新建的工具）
const expandedTools = ref<Set<number>>(new Set())

// 图片上传相关
const uploadedImages = ref<string[]>([])  // base64 图片列表
const isUploading = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

// 最大图片大小 10MB
const MAX_IMAGE_SIZE = 10 * 1024 * 1024

// 消息分组（Slack 风格）
const messageGroups = computed<MessageGroup[]>(() => {
  const groups: MessageGroup[] = []

  for (const msg of messages.value) {
    const lastGroup = groups[groups.length - 1]

    if (lastGroup && lastGroup.role === msg.role) {
      lastGroup.messages.push(msg)
    } else {
      groups.push({
        role: msg.role,
        messages: [msg]
      })
    }
  }

  return groups
})

// 获取最新助手消息内容（用于语音播报）
const currentAssistantContent = computed(() => {
  const lastMsg = messages.value[messages.value.length - 1]
  if (lastMsg?.role === 'assistant') {
    // 如果有分段，取文本段内容
    if (lastMsg.segments) {
      for (const seg of lastMsg.segments) {
        if (seg.type === 'text' && seg.content) {
          return seg.content
        }
      }
    }
    // 否则取 content
    return lastMsg.content
  }
  return ''
})

// 是否应该显示加载指示器（底部的独立指示器）
// 只有当助手消息组完全没有可见内容时才显示
const shouldShowLoadingIndicator = computed(() => {
  if (messages.value.length === 0) {
    return true
  }

  const lastMsg = messages.value[messages.value.length - 1]
  if (lastMsg?.role !== 'assistant') {
    return true
  }

  // 只有当完全没有可见内容时才显示底部指示器
  // 如果有工具卡片等可见内容，等待状态会在消息组内部显示
  return !hasVisibleContent(lastMsg)
})

// 检查消息组是否有可见内容
const hasGroupVisibleContent = (group: MessageGroup): boolean => {
  for (const msg of group.messages) {
    if (hasVisibleContent(msg)) {
      return true
    }
  }
  return false
}

// 检查消息组是否有文本内容
const hasGroupTextContent = (group: MessageGroup): boolean => {
  for (const msg of group.messages) {
    if (hasTextContent(msg)) {
      return true
    }
  }
  return false
}

// 检查消息组是否有正在执行或已完成的工具（但还没有文本回复）
const hasGroupToolWithoutText = (group: MessageGroup): boolean => {
  if (group.role !== 'assistant') return false
  let hasTool = false
  let hasText = false
  for (const msg of group.messages) {
    if (!msg.segments) continue
    for (const segment of msg.segments) {
      if (segment.type === 'tool' && !getToolConfig(segment.tool).hidden) {
        hasTool = true
      }
      if (segment.type === 'text' && segment.content && segment.content.trim()) {
        hasText = true
      }
    }
  }
  return hasTool && !hasText
}

// 保存当前会话 ID 到 localStorage
const saveCurrentSession = (sessionId: string) => {
  localStorage.setItem(SESSION_STORAGE_KEY, sessionId)
}

// 从 localStorage 读取上次会话 ID
const getLastSession = (): string | null => {
  return localStorage.getItem(SESSION_STORAGE_KEY)
}

// 加载会话历史（按照 OpenAI 标准格式解析）
const loadSessionHistory = async (sessionId: string) => {
  try {
    const res = await sessionApi.getHistory(sessionId)
    const rawMessages = res.messages

    // 用于存储工具调用结果（tool_call_id -> result）
    const toolResults: Map<string, string> = new Map()

    // 第一遍：收集所有 tool 消息的结果
    for (const msg of rawMessages) {
      if (msg.role === 'tool' && msg.tool_call_id && msg.content) {
        toolResults.set(msg.tool_call_id, msg.content)
      }
    }

    // 第二遍：构建显示消息
    const displayMessages: Message[] = []
    let pendingAssistant: Message | null = null

    for (let i = 0; i < rawMessages.length; i++) {
      const msg = rawMessages[i]!

      if (msg.role === 'user') {
        // 如果有待处理的 assistant 消息，先添加
        if (pendingAssistant) {
          displayMessages.push(pendingAssistant)
          pendingAssistant = null
        }
        // 添加 user 消息
        displayMessages.push({
          id: Date.now() + i,
          role: 'user',
          content: msg.content || '',
          timestamp: new Date()
        })
      }
      else if (msg.role === 'assistant') {
        if (msg.tool_calls && msg.tool_calls.length > 0) {
          // 包含工具调用的 assistant 消息
          const segments: MessageSegment[] = []

          // 添加工具调用段
          msg.tool_calls.forEach((tc, tcIndex) => {
            const result = toolResults.get(tc.id)
            segments.push({
              type: 'tool',
              id: Date.now() + i * 1000 + tcIndex,
              tool: tc.function.name,
              args: JSON.parse(tc.function.arguments || '{}'),
              result: result,
              status: result?.startsWith('❌') ? 'error' : 'done'
            })
          })

          // 检查下一个消息是否是最终的 assistant 回答（没有 tool_calls）
          const nextMsg = rawMessages[i + 1]
          if (nextMsg && nextMsg.role === 'assistant' && !nextMsg.tool_calls && nextMsg.content) {
            // 有最终回答，添加文本段
            segments.push({
              type: 'text',
              id: Date.now() + i * 1000 + 100,
              content: nextMsg.content
            })
            i++ // 跳过下一个消息
          }

          pendingAssistant = {
            id: Date.now() + i,
            role: 'assistant',
            content: '',
            timestamp: new Date(),
            segments
          }
        } else if (msg.content) {
          // 普通的 assistant 文本消息
          if (pendingAssistant) {
            // 追加到待处理的 assistant 消息
            if (!pendingAssistant.segments) {
              pendingAssistant.segments = []
            }
            pendingAssistant.segments.push({
              type: 'text',
              id: Date.now() + i,
              content: msg.content
            })
          } else {
            // 新的 assistant 消息
            displayMessages.push({
              id: Date.now() + i,
              role: 'assistant',
              content: msg.content,
              timestamp: new Date()
            })
          }
        }
      }
      // tool 消息在第一遍已经处理，跳过
    }

    // 添加最后的待处理消息
    if (pendingAssistant) {
      displayMessages.push(pendingAssistant)
    }

    messages.value = displayMessages
    setTimeout(scrollToBottom, 50)
  } catch (error) {
    // 会话不存在或加载失败，清空消息
    messages.value = []
  }
}

// 初始化会话
const initSession = async () => {
  // 获取助手名字
  try {
    const agentInfo = await configApi.getAgentInfo()
    if (agentInfo.name) {
      assistantName.value = agentInfo.name
    }
  } catch (error) {
    // 获取失败时使用默认名字
    console.warn('获取助手名字失败:', error)
  }

  const urlSession = route.query.session as string | undefined

  if (urlSession) {
    // URL 中有 session 参数，使用它
    currentSessionId.value = urlSession
    saveCurrentSession(urlSession)
    await loadSessionHistory(urlSession)
    initializing.value = false
  } else {
    // URL 中没有 session 参数，尝试从 localStorage 读取
    const lastSession = getLastSession()
    if (lastSession) {
      // 有上次会话，设置 session 并加载历史，然后更新 URL
      currentSessionId.value = lastSession
      saveCurrentSession(lastSession)
      await loadSessionHistory(lastSession)
      // 使用 replace 更新 URL（不触发导航）
      window.history.replaceState({}, '', `/?session=${lastSession}`)
      initializing.value = false
    } else {
      // 没有上次会话，创建新会话
      try {
        const res = await sessionApi.create()
        saveCurrentSession(res.session_id)
        currentSessionId.value = res.session_id
        // 使用 replace 更新 URL（不触发导航）
        window.history.replaceState({}, '', `/?session=${res.session_id}`)
        initializing.value = false
      } catch (error) {
        message.error('创建会话失败')
        initializing.value = false
      }
    }
  }
}

// 监听 session 参数变化（处理从其他地方跳转过来的情况）
watch(
  () => route.query.session,
  async (newSession, oldSession) => {
    // 如果正在初始化，跳过
    if (initializing.value) return

    // 如果 session 没有实际变化，跳过
    if (newSession === oldSession) return

    const sessionId = (newSession as string) || null

    // 如果新 session 为空，不做处理（应该由 initSession 处理）
    if (!sessionId) return

    // 切换到新会话
    currentSessionId.value = sessionId
    saveCurrentSession(sessionId)
    inputMessage.value = ''
    await loadSessionHistory(sessionId)
  }
)

// 监听 refresh 参数变化（处理从配置页面初始化后跳转的情况）
watch(
  () => route.query.refresh,
  async (newRefresh) => {
    if (newRefresh) {
      // 重新获取助手名字
      try {
        const agentInfo = await configApi.getAgentInfo()
        if (agentInfo.name) {
          assistantName.value = agentInfo.name
        }
      } catch (error) {
        console.warn('获取助手名字失败:', error)
      }

      // 清除 URL 中的 refresh 参数
      const currentQuery = { ...route.query }
      delete currentQuery.refresh
      router.replace({ query: currentQuery })
    }
  }
)

// 组件挂载时初始化会话
onMounted(async () => {
  await initSession()
})

// 滚动到底部
const scrollToBottom = async () => {
  await nextTick()
  if (messagesContainer.value) {
    requestAnimationFrame(() => {
      if (messagesContainer.value) {
        messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
      }
    })
  }
}

// 切换工具折叠状态
const toggleToolCollapse = (toolId: number) => {
  if (expandedTools.value.has(toolId)) {
    expandedTools.value.delete(toolId)
  } else {
    expandedTools.value.add(toolId)
  }
}

// 检查工具是否展开（默认折叠，只有点击后才展开）
const isToolExpanded = (toolId: number): boolean => {
  return expandedTools.value.has(toolId)
}

// 检查消息是否有可见内容
const hasVisibleContent = (msg: Message): boolean => {
  if (!msg.segments || msg.segments.length === 0) {
    // 没有分段，检查普通内容
    return !!msg.content
  }

  // 有分段，检查是否有可见的段
  for (const segment of msg.segments) {
    if (segment.type === 'text' && segment.content) {
      return true
    }
    if (segment.type === 'tool' && !getToolConfig(segment.tool).hidden) {
      return true
    }
  }
  return false
}

// 检查消息是否有文本内容（用于决定是否显示加载指示器）
const hasTextContent = (msg: Message): boolean => {
  if (!msg.segments || msg.segments.length === 0) {
    return !!msg.content
  }
  // 只检查文本段
  for (const segment of msg.segments) {
    if (segment.type === 'text' && segment.content) {
      return true
    }
  }
  return false
}

// 检查消息是否有可见的工具调用（用于决定是否显示工具卡片而非加载指示器）
const hasVisibleTools = (msg: Message): boolean => {
  if (!msg.segments) return false
  for (const segment of msg.segments) {
    if (segment.type === 'tool' && !getToolConfig(segment.tool).hidden) {
      return true
    }
  }
  return false
}

// 检查消息组是否正在等待响应（用于隐藏 group-footer）
const isGroupWaiting = (group: MessageGroup): boolean => {
  if (group.role !== 'assistant' || !loading.value) return false
  // 检查组内所有消息是否都没有文本内容
  return group.messages.every(msg => !hasTextContent(msg))
}

// 停止生成
const stopGeneration = () => {
  if (abortController.value) {
    abortController.value.abort()
    abortController.value = null
    loading.value = false
  }
}

// 更新消息段（触发 Vue 响应性）
const updateMessageSegments = (msgIndex: number, segments: MessageSegment[]) => {
  if (msgIndex >= 0 && msgIndex < messages.value.length) {
    const existingMsg = messages.value[msgIndex]!
    messages.value[msgIndex] = {
      id: existingMsg.id,
      role: existingMsg.role,
      content: existingMsg.content,
      timestamp: existingMsg.timestamp,
      segments: [...segments]
    }
  }
}

const sendMessage = async () => {
  if (!inputMessage.value.trim() && uploadedImages.value.length === 0) return

  const userMessage = inputMessage.value
  const userMsg: Message = {
    id: Date.now(),
    role: 'user',
    content: userMessage,
    timestamp: new Date(),
    images: uploadedImages.value.length > 0 ? [...uploadedImages.value] : undefined
  }

  messages.value.push(userMsg)
  inputMessage.value = ''
  loading.value = true

  // 保存当前图片并在发送后清除
  const currentImages = [...uploadedImages.value]
  uploadedImages.value = []

  // 创建 AbortController
  abortController.value = new AbortController()

  // 助手消息的索引和段
  let assistantMsgIndex = -1
  let currentSegments: MessageSegment[] = []
  let currentTextSegmentId = -1

  await scrollToBottom()

  try {
    await chatApi.sendMessageStream(
      userMessage,
      currentSessionId.value || undefined,
      (event) => {
        if (event.type === 'session') {
          // 收到会话 ID
          if (event.session_id) {
            currentSessionId.value = event.session_id
            saveCurrentSession(event.session_id)
          }
        } else if (event.type === 'step_start') {
          // 新步骤开始 - 创建新的文本段
          currentTextSegmentId = Date.now()
          currentSegments.push({
            type: 'text',
            id: currentTextSegmentId,
            content: ''
          })

          // 如果还没有助手消息，创建一个
          if (assistantMsgIndex === -1) {
            assistantMsgIndex = messages.value.length
            messages.value.push({
              id: Date.now(),
              role: 'assistant',
              content: '',
              timestamp: new Date(),
              segments: currentSegments
            })
          } else {
            updateMessageSegments(assistantMsgIndex, currentSegments)
          }
          scrollToBottom()
        } else if (event.type === 'chunk' && event.content) {
          // 更新当前文本段
          const textSegment = currentSegments.find(s => s.type === 'text' && s.id === currentTextSegmentId) as TextSegment | undefined
          if (textSegment) {
            textSegment.content += event.content
            updateMessageSegments(assistantMsgIndex, currentSegments)
          }
          scrollToBottom()
        } else if (event.type === 'tool_start') {
          // 工具调用开始 - 创建工具段
          currentSegments.push({
            type: 'tool',
            id: Date.now(),
            tool: event.tool || '',
            args: event.args || {},
            status: 'running'
          })

          // 如果还没有助手消息，创建一个
          if (assistantMsgIndex === -1) {
            assistantMsgIndex = messages.value.length
            messages.value.push({
              id: Date.now(),
              role: 'assistant',
              content: '',
              timestamp: new Date(),
              segments: currentSegments
            })
          } else {
            updateMessageSegments(assistantMsgIndex, currentSegments)
          }
          scrollToBottom()
        } else if (event.type === 'tool_finish') {
          // 工具调用结束 - 查找或创建工具段
          const lastToolSegment = [...currentSegments].reverse().find(s => s.type === 'tool' && s.status === 'running') as ToolSegment | undefined
          if (lastToolSegment) {
            // 更新现有的运行中工具
            lastToolSegment.result = event.result
            lastToolSegment.status = 'done'
          } else {
            // 没有对应的 tool_start，直接添加为完成的工具
            currentSegments.push({
              type: 'tool',
              id: Date.now(),
              tool: event.tool || '',
              args: {},
              result: event.result,
              status: 'done'
            })
          }
          updateMessageSegments(assistantMsgIndex, currentSegments)
          scrollToBottom()
        } else if (event.type === 'done') {
          // 完成
          if (event.session_id) {
            currentSessionId.value = event.session_id
          }
          // 对话结束后重新获取助手名字（可能在对话中更新了 IDENTITY.md）
          configApi.getAgentInfo().then(agentInfo => {
            if (agentInfo.name) {
              assistantName.value = agentInfo.name
            }
          }).catch(() => {
            // 忽略错误，保持当前名字
          })
        } else if (event.type === 'error') {
          message.error(event.error || '发送消息失败')
        }
      },
      abortController.value.signal,
      currentImages.length > 0 ? currentImages : undefined
    )

    await scrollToBottom()
  } catch (error: unknown) {
    // 如果是用户主动取消，不显示错误
    if (error instanceof Error && error.name === 'AbortError') {
      console.log('用户取消了请求')
      // 取消时保留已生成的内容
    } else {
      console.error('发送消息失败:', error)
      message.error('发送消息失败')
      // 移除用户消息
      messages.value.pop()
    }
  } finally {
    loading.value = false
    abortController.value = null
  }
}

const createNewSession = async () => {
  try {
    const res = await sessionApi.create()
    saveCurrentSession(res.session_id)
    router.push({ name: 'chat', query: { session: res.session_id } })
  } catch (error) {
    message.error('新建会话失败')
  }
}

const getImageUrl = (url: string) => {
  if (!url) return '';
  if (url.startsWith('data:') || url.startsWith('blob:') || url.startsWith('http')) return url;
  // Fallback dev backend relative path
  const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';
  return `${baseUrl}/chat/${url}`;
}

// 处理图片选择
const handleImageSelect = async (event: Event) => {
  const input = event.target as HTMLInputElement
  if (!input.files || input.files.length === 0) return

  const files = Array.from(input.files)

  for (const file of files) {
    // 检查文件大小
    if (file.size > MAX_IMAGE_SIZE) {
      message.warning(`${file.name} 超过 10MB 限制，已跳过`)
      continue
    }

    // 检查文件类型
    if (!file.type.startsWith('image/')) {
      message.warning(`${file.name} 不是图片文件，已跳过`)
      continue
    }

    try {
      const res = await chatApi.uploadFile(file)
      uploadedImages.value.push(res.url)
    } catch (error) {
      console.error('图片上传失败:', error)
      message.error(`${file.name} 上传失败`)
    }
  }

  // 清空 input 以允许重新选择同一文件
  if (fileInputRef.value) {
    fileInputRef.value.value = ''
  }
}

// 移除图片
const removeImage = (index: number) => {
  uploadedImages.value.splice(index, 1)
}

// 触发文件选择
const triggerFileSelect = () => {
  fileInputRef.value?.click()
}

// 语音输入功能 (Web Speech API)
const isRecording = ref(false)
let speechRecognition: SpeechRecognition | null = null

const initSpeechRecognition = () => {
  const SpeechRecognition = window.SpeechRecognition || (window as any).webkitSpeechRecognition
  if (!SpeechRecognition) {
    message.warning('您的浏览器不支持语音输入，建议使用 Chrome 浏览器')
    return null
  }
  
  const recognition = new SpeechRecognition()
  recognition.continuous = false
  recognition.interimResults = true
  recognition.lang = 'zh-CN'
  
  return recognition
}

const startRecording = () => {
  if (!speechRecognition) {
    speechRecognition = initSpeechRecognition()
  }
  
  if (!speechRecognition) return
  
  speechRecognition.onstart = () => {
    isRecording.value = true
    message.info('开始语音输入...')
  }
  
  speechRecognition.onresult = (event: SpeechRecognitionEvent) => {
    let finalTranscript = ''
    let interimTranscript = ''
    
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript
      if (event.results[i].isFinal) {
        finalTranscript += transcript
      } else {
        interimTranscript += transcript
      }
    }
    
    if (finalTranscript) {
      inputMessage.value += finalTranscript
    }
  }
  
  speechRecognition.onerror = (event: SpeechRecognitionErrorEvent) => {
    console.error('语音识别错误:', event.error)
    isRecording.value = false
    if (event.error !== 'no-speech') {
      message.error(`语音识别错误: ${event.error}`)
    }
  }
  
  speechRecognition.onend = () => {
    isRecording.value = false
  }
  
  speechRecognition.start()
}

const stopRecording = () => {
  if (speechRecognition) {
    speechRecognition.stop()
    isRecording.value = false
  }
}

// 语音输出功能 (Web Speech API TTS)
const isSpeaking = ref(false)

const speakText = (text: string) => {
  if (!('speechSynthesis' in window)) {
    message.warning('您的浏览器不支持语音合成')
    return
  }
  
  // 停止当前正在播放的语音
  window.speechSynthesis.cancel()
  
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'zh-CN'
  utterance.rate = 1.0
  utterance.pitch = 1.0
  
  utterance.onstart = () => {
    isSpeaking.value = true
  }
  
  utterance.onend = () => {
    isSpeaking.value = false
  }
  
  utterance.onerror = () => {
    isSpeaking.value = false
  }
  
  window.speechSynthesis.speak(utterance)
}

const stopSpeaking = () => {
  window.speechSynthesis.cancel()
  isSpeaking.value = false
}

// 页面卸载时停止语音
onUnmounted(() => {
  if (speechRecognition) {
    speechRecognition.stop()
  }
  window.speechSynthesis.cancel()
})
</script>

<template>
  <div class="chat-view">
    <!-- 消息区域 -->
    <div class="chat-messages" ref="messagesContainer">
      <!-- 初始化加载状态 -->
      <div v-if="initializing" class="empty-state">
        <img :src="LobsterIcon" alt="HelloClaw" class="empty-icon loading" />
        <p class="empty-hint">加载中...</p>
      </div>
      <template v-else-if="messages.length > 0">
        <div
          v-for="(group, groupIndex) in messageGroups"
          :key="groupIndex"
          v-show="group.role !== 'assistant' || hasGroupVisibleContent(group)"
          :class="['message-group', group.role]"
        >
          <!-- 头像 -->
          <div class="group-avatar">
            <img v-if="group.role === 'assistant'" :src="LobsterIcon" alt="HelloClaw" />
            <div v-else class="user-avatar">你</div>
          </div>

          <!-- 消息内容 -->
          <div class="group-content">
            <!-- 遍历每条消息 -->
            <template v-for="(msg, msgIndex) in group.messages" :key="msg.id">
              <!-- 如果有分段，按分段显示 -->
              <template v-if="msg.segments && msg.segments.length > 0">
                <template v-for="segment in msg.segments" :key="segment.id">
                  <!-- 文本段 -->
                  <div v-if="segment.type === 'text' && segment.content" class="message-bubble">
                    <div
                      class="message-text"
                      v-html="renderMarkdown(segment.content)"
                    ></div>
                  </div>
                  <!-- 工具调用段 - 只显示非隐藏的工具 -->
                  <div
                    v-if="segment.type === 'tool' && !getToolConfig(segment.tool).hidden"
                    :class="['tool-card', segment.status]"
                  >
                    <div
                      class="tool-header"
                      @click="segment.status !== 'running' && toggleToolCollapse(segment.id)"
                    >
                      <span class="tool-icon">{{ getToolConfig(segment.tool).icon }}</span>
                      <span class="tool-name">
                        <template v-if="!isToolExpanded(segment.id)">使用了</template>
                        {{ getToolConfig(segment.tool).name }}
                      </span>
                      <Tag v-if="segment.status === 'running'" color="processing" class="tool-tag">
                        <LoadingOutlined /> 执行中
                      </Tag>
                      <Tag v-else-if="segment.status === 'done'" color="success" class="tool-tag">完成</Tag>
                      <Tag v-else-if="segment.status === 'error'" color="error" class="tool-tag">失败</Tag>
                      <span
                        v-if="segment.status !== 'running'"
                        class="collapse-indicator"
                      >
                        {{ isToolExpanded(segment.id) ? '▼' : '▶' }}
                      </span>
                    </div>
                    <!-- 展开后显示入参和结果 -->
                    <div v-if="isToolExpanded(segment.id)" class="tool-details">
                      <!-- 入参 -->
                      <div v-if="segment.args && Object.keys(segment.args).length > 0" class="tool-args">
                        <div class="tool-detail-label">入参</div>
                        <pre class="tool-detail-content">{{ formatToolArgs(segment.args) }}</pre>
                      </div>
                      <!-- 结果 -->
                      <div v-if="segment.result" class="tool-result-wrapper">
                        <div class="tool-detail-label">结果</div>
                        <pre class="tool-detail-content">{{ formatToolResult(segment.result) }}</pre>
                      </div>
                    </div>
                  </div>
                </template>
              </template>
              <!-- 如果没有分段，显示普通内容（历史消息） -->
              <template v-if="msg.role === 'user'">
                <!-- 用户消息：显示图片 -->
                <div v-if="msg.images && msg.images.length > 0" class="message-images">
                  <div v-for="(img, imgIdx) in msg.images" :key="imgIdx" class="message-image-item">
                    <img :src="getImageUrl(img)" class="message-image" />
                  </div>
                </div>
                <!-- 用户消息：显示文本 -->
                <div v-if="msg.content" class="message-bubble">
                  <div
                    class="message-text"
                    v-html="renderMarkdown(msg.content)"
                  ></div>
                </div>
              </template>
              <!-- 助手消息：显示文本 -->
              <div v-else-if="msg.content" class="message-bubble">
                <div
                  class="message-text"
                  v-html="renderMarkdown(msg.content)"
                ></div>
              </div>
            </template>

            <!-- 消息组内部的等待状态（有工具调用但没有文本回复时） -->
            <div v-if="loading && hasGroupToolWithoutText(group)" class="message-bubble">
              <div class="loading-dots">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>

            <!-- 组底部：名称和时间（加载等待时隐藏） -->
            <div v-if="!isGroupWaiting(group)" class="group-footer">
              <span class="group-name">{{ group.role === 'user' ? '你' : assistantName }}</span>
              <span class="group-time">{{ formatTime(group.messages[group.messages.length - 1]?.timestamp || new Date()) }}</span>
            </div>
          </div>
        </div>
      </template>

      <!-- 空状态 -->
      <div v-else class="empty-state">
        <img :src="LobsterIcon" alt="HelloClaw" class="empty-icon" />
        <p class="empty-hint">发送消息开始对话</p>
      </div>

      <!-- 加载指示器（助手消息组样式）- 等待响应时显示 -->
      <div v-if="loading && shouldShowLoadingIndicator" class="message-group assistant loading-group">
        <div class="group-avatar">
          <img :src="LobsterIcon" alt="HelloClaw" />
        </div>
        <div class="group-content">
          <div class="message-bubble">
            <div class="loading-dots">
              <span></span>
              <span></span>
              <span></span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="chat-input-wrapper">
      <!-- 图片预览区域 -->
      <div v-if="uploadedImages.length > 0" class="image-preview-container">
        <div v-for="(img, index) in uploadedImages" :key="index" class="image-preview-item">
          <img :src="getImageUrl(img)" class="image-preview-img" />
          <button class="image-remove-btn" @click="removeImage(index)" title="移除">×</button>
        </div>
      </div>
      
      <div class="chat-input">
        <!-- 隐藏的文件输入 -->
        <input
          ref="fileInputRef"
          type="file"
          accept="image/*"
          multiple
          style="display: none"
          @change="handleImageSelect"
        />
        
        <!-- 输入框 -->
        <Input.TextArea
          v-model:value="inputMessage"
          placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
          :auto-size="{ minRows: 1, maxRows: 4 }"
          @press-enter="(e: KeyboardEvent) => { if (!e.shiftKey) { e.preventDefault(); sendMessage() } }"
        />
        <!-- 按钮区域（固定宽度） -->
        <div class="input-actions">
          <!-- 语音输入按钮 -->
          <Button
            v-if="!isRecording"
            class="icon-btn voice-btn"
            @click="startRecording"
            title="语音输入"
          >
            <template #icon>
              <AudioOutlined />
            </template>
          </Button>
          <!-- 录音中按钮 -->
          <Button
            v-else
            class="icon-btn voice-btn recording"
            @click="stopRecording"
            title="停止录音"
          >
            <template #icon>
              <AudioFilled />
            </template>
          </Button>
          <!-- 语音输出按钮 -->
          <Button
            v-if="!isSpeaking"
            class="icon-btn"
            @click="currentAssistantContent && speakText(currentAssistantContent)"
            :disabled="!currentAssistantContent"
            title="语音播报"
          >
            <template #icon>
              <span class="voice-icon">🔊</span>
            </template>
          </Button>
          <!-- 停止播报按钮 -->
          <Button
            v-else
            class="icon-btn"
            @click="stopSpeaking"
            title="停止播报"
          >
            <template #icon>
              <span class="voice-icon">🔇</span>
            </template>
          </Button>
          <!-- 图片上传按钮 -->
          <Button
            class="icon-btn"
            @click="triggerFileSelect"
            title="上传图片"
          >
            <template #icon>
              <span class="image-icon">📷</span>
            </template>
          </Button>
          <!-- 新建会话按钮 -->
          <Button
            class="icon-btn"
            @click="createNewSession"
            title="新建会话"
          >
            <template #icon>
              <PlusOutlined />
            </template>
          </Button>
          <!-- 停止按钮（loading 时显示） -->
          <button
            v-if="loading"
            class="stop-btn"
            @click="stopGeneration"
            title="停止生成"
          >
            <div class="stop-icon"></div>
          </button>
          <!-- 发送按钮（有文字或图片时显示） -->
          <button
            v-else-if="inputMessage.trim() || uploadedImages.length > 0"
            class="send-btn active"
            @click="sendMessage"
            title="发送消息"
          >
            <SendOutlined />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  box-sizing: border-box;
  background-color: transparent;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 32px 40px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* 消息入场动画 */
@keyframes slideInUp {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 消息组样式 */
.message-group {
  display: flex;
  gap: 16px;
  max-width: 85%;
  animation: slideInUp 0.4s cubic-bezier(0.165, 0.84, 0.44, 1) forwards;
}

.message-group.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.message-group.assistant {
  align-self: flex-start;
}

/* 头像 */
.group-avatar {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
}

.group-avatar img {
  width: 36px;
  height: 36px;
  border-radius: 8px;
}

.user-avatar {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background-color: var(--color-primary);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 消息组内容 */
.group-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

/* 消息气泡 */
.message-bubble {
  display: inline-block;
  max-width: 100%;
  transition: transform 0.2s ease;
}

.message-bubble:hover {
  transform: translateY(-2px);
}

.message-text {
  padding: 14px 20px;
  border-radius: 20px;
  background-color: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(10px);
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.03), 0 1px 3px rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.5);
  line-height: 1.7;
  word-wrap: break-word;
  color: #2c3e50;
  font-size: 15px;
}

.message-group.user .message-text {
  background: linear-gradient(135deg, #ff758c, #ff7eb3);
  color: white;
  border: none;
  box-shadow: 0 4px 15px rgba(255, 117, 140, 0.3);
  border-bottom-right-radius: 4px;
}

.message-group.assistant .message-text {
  border-bottom-left-radius: 4px;
}

/* Markdown 样式 */
.message-text :deep(p) {
  margin: 0;
}

.message-text :deep(p + p) {
  margin-top: 8px;
}

.message-text :deep(code) {
  background-color: rgba(0, 0, 0, 0.05);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}

.message-text :deep(pre) {
  background-color: #1e1e1e;
  color: #d4d4d4;
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
}

.message-text :deep(pre code) {
  background-color: transparent;
  padding: 0;
}

.message-text :deep(ul),
.message-text :deep(ol) {
  margin: 8px 0;
  padding-left: 20px;
}

.message-text :deep(blockquote) {
  border-left: 3px solid var(--color-primary);
  padding-left: 12px;
  margin: 8px 0;
  color: var(--color-text-secondary);
}

.message-text :deep(a) {
  color: var(--color-primary);
  text-decoration: underline;
}

/* 组底部 */
.group-footer {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 4px;
  padding-left: 4px;
}

.group-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text);
}

.group-time {
  font-size: 11px;
  color: var(--color-text-secondary);
}

/* 空状态 */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
}

.empty-icon {
  width: 100px;
  height: 100px;
  opacity: 0.5;
}

.empty-icon.loading {
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 0.3;
    transform: scale(0.95);
  }
  50% {
    opacity: 0.6;
    transform: scale(1);
  }
}

.empty-hint {
  color: var(--color-text-secondary);
  font-size: 14px;
}

/* 加载指示器 */
.loading-group .message-bubble,
.message-bubble:has(.loading-dots) {
  padding: 14px 12px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 8px;
}

.loading-dots {
  display: flex;
  gap: 4px;
  align-items: center;
}

.loading-dots span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: var(--color-primary);
  animation: loading-pulse 1.4s ease-in-out infinite;
}

.loading-dots span:nth-child(2) {
  animation-delay: 0.2s;
}

.loading-dots span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes loading-pulse {
  0%, 100% {
    opacity: 0.4;
    transform: scale(0.8);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}

/* 输入区域 悬浮胶囊 */
.chat-input-wrapper {
  padding: 0 40px 32px;
  background-color: transparent;
  border-top: none;
  position: relative;
}

.chat-input {
  display: flex;
  gap: 12px;
  align-items: center;
  max-width: 800px;
  margin: 0 auto;
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.6);
  border-radius: 24px;
  padding: 8px 12px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
  transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
}

.chat-input:focus-within {
  box-shadow: 0 12px 40px rgba(255, 117, 140, 0.15), 0 0 0 2px rgba(255, 117, 140, 0.2);
  transform: translateY(-2px);
}

.chat-input :deep(.ant-input) {
  flex: 1;
  border-radius: 16px;
  padding: 10px 16px;
  resize: none;
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  font-size: 15px;
}

/* 按钮区域（固定宽度，防止输入框抖动） */
.input-actions {
  flex-shrink: 0;
  display: flex;
  gap: 12px;
  align-items: center;
  width: 92px;
}

/* 新建会话按钮 */
.input-actions .icon-btn {
  width: 40px;
  height: 40px;
  padding: 0;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-secondary);
}

.input-actions .icon-btn:hover {
  background: var(--color-primary-light);
  border-color: var(--color-primary);
  color: var(--color-primary);
}

/* 发送按钮 - 白底 + 黑色图标，输入后红底 + 白色图标 */
.input-actions .send-btn {
  width: 40px;
  height: 40px;
  padding: 0;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
  color: #333;
}

.input-actions .send-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

/* 输入文字后：红底 + 白色图标 */
.input-actions .send-btn.active {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: #fff;
}

.input-actions .send-btn.active:hover {
  background: var(--color-primary-hover);
  border-color: var(--color-primary-hover);
}

/* 停止按钮 - 红底 + 白色圆角方块图标 */
.input-actions .stop-btn {
  width: 40px;
  height: 40px;
  padding: 0;
  border: none;
  border-radius: 8px;
  background: var(--color-primary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
}

.input-actions .stop-btn:hover {
  background: var(--color-primary-hover);
}

.stop-icon {
  width: 14px;
  height: 14px;
  background: #fff;
  border-radius: 3px;
}

/* 工具调用卡片 */
.tool-calls {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}

.tool-card {
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.4);
  border-radius: 12px;
  padding: 10px 14px;
  font-size: 13px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.02);
  transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
}

.tool-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

/* 执行中状态 - 龙虾红主题 */
.tool-card.running {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.tool-card.running .tool-icon,
.tool-card.running .tool-name {
  color: var(--color-primary);
}

/* 完成状态 - 灰色调 */
.tool-card.done {
  border-color: var(--color-border);
  background: var(--color-surface);
}

/* 失败状态 - 红色调 */
.tool-card.error {
  border-color: var(--color-primary);
  background: #fff1f0;
}

.tool-card.error .tool-icon,
.tool-card.error .tool-name {
  color: var(--color-primary);
}

.tool-header {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}

.tool-header:hover {
  opacity: 0.8;
}

.tool-icon {
  font-size: 14px;
  line-height: 1;
}

.tool-name {
  font-weight: 500;
  color: var(--color-text);
  flex: 1;
}

.tool-tag {
  font-size: 11px;
  padding: 0 6px;
  line-height: 18px;
  border-radius: 4px;
}

.collapse-indicator {
  font-size: 10px;
  color: var(--color-text-secondary);
  margin-left: auto;
  transition: transform 0.2s ease;
}

/* 工具详情区域 */
.tool-details {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--color-border);
}

.tool-args,
.tool-result-wrapper {
  margin-bottom: 8px;
}

.tool-result-wrapper:last-child {
  margin-bottom: 0;
}

.tool-detail-label {
  font-size: 11px;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
  font-weight: 500;
}

.tool-detail-content {
  margin: 0;
  padding: 8px;
  background: rgba(0, 0, 0, 0.02);
  border-radius: 4px;
  font-size: 12px;
  color: var(--color-text);
  max-height: 150px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, 'SF Mono', Monaco, 'Andale Mono', monospace;
}

.step-info {
  color: var(--color-text-secondary);
  font-size: 11px;
}

/* 图片上传预览 */
.image-preview-container {
  display: flex;
  gap: 8px;
  padding: 8px 40px;
  max-width: 800px;
  margin: 0 auto;
  overflow-x: auto;
}

.image-preview-item {
  position: relative;
  flex-shrink: 0;
  width: 60px;
  height: 60px;
  border-radius: 8px;
  overflow: hidden;
  border: 2px solid var(--color-border);
}

.image-preview-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.image-remove-btn {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.6);
  color: white;
  border: none;
  cursor: pointer;
  font-size: 12px;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.image-remove-btn:hover {
  background: rgba(255, 0, 0, 0.8);
}

/* 图片上传按钮图标 */
.image-icon {
  font-size: 16px;
}

/* 用户消息中的图片 */
.message-images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.message-image-item {
  width: 120px;
  height: 120px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--color-border);
}

.message-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
</style>
