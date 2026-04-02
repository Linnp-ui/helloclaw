<script setup lang="ts">
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { Menu, ConfigProvider, theme } from 'ant-design-vue'
import { MessageOutlined, SettingOutlined, HistoryOutlined, BookOutlined } from '@ant-design/icons-vue'
import LobsterIcon from '@/assets/lobster.svg'

const route = useRoute()

// 龙虾红主题配置
const customTheme = {
  token: {
    colorPrimary: '#ff5c5c',
    colorPrimaryHover: '#ff7070',
    colorPrimaryActive: '#e64a4a',
    colorPrimaryBg: 'rgba(255, 92, 92, 0.1)',
    colorPrimaryBgHover: 'rgba(255, 92, 92, 0.2)',
  },
}
</script>

<template>
  <ConfigProvider :theme="{ token: customTheme.token }">
    <div class="app-container">
      <aside class="sidebar">
        <div class="logo">
          <img :src="LobsterIcon" alt="HelloClaw" class="logo-icon" />
          <span class="logo-text">HelloClaw</span>
        </div>
        <Menu
          mode="inline"
          :selected-keys="[route.name as string]"
          class="sidebar-menu"
        >
          <Menu.Item key="chat">
            <RouterLink to="/">
              <MessageOutlined />
              <span>聊天</span>
            </RouterLink>
          </Menu.Item>
          <Menu.Item key="sessions">
            <RouterLink to="/sessions">
              <HistoryOutlined />
              <span>会话</span>
            </RouterLink>
          </Menu.Item>
          <Menu.Item key="memory">
            <RouterLink to="/memory">
              <BookOutlined />
              <span>记忆</span>
            </RouterLink>
          </Menu.Item>
          <Menu.Item key="config">
            <RouterLink to="/config">
              <SettingOutlined />
              <span>配置</span>
            </RouterLink>
          </Menu.Item>
        </Menu>
      </aside>

      <main class="main-content">
        <RouterView />
      </main>
    </div>
  </ConfigProvider>
</template>

<style scoped>
/* 全局动效背景 */
@keyframes gradientBG {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}

.app-container {
  display: flex;
  height: 100vh;
  overflow: hidden;
  /* 高级渐变背景 */
  background: linear-gradient(-45deg, #fff3f3, #f5f0ff, #eef5ff, #fff0f5);
  background-size: 400% 400%;
  animation: gradientBG 15s ease infinite;
}

.sidebar {
  width: 240px;
  /* 玻璃拟态 (Glassmorphism) */
  background-color: rgba(255, 255, 255, 0.65);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-right: 1px solid rgba(255, 255, 255, 0.8);
  box-shadow: 2px 0 15px rgba(0, 0, 0, 0.02);
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.logo {
  padding: 24px 20px;
  display: flex;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
}

.logo-icon {
  width: 38px;
  height: 38px;
  filter: drop-shadow(0 4px 6px rgba(255, 92, 92, 0.3));
  transition: transform 0.3s ease;
}

.logo:hover .logo-icon {
  transform: scale(1.1) rotate(-5deg);
}

.logo-text {
  font-size: 20px;
  font-weight: 700;
  background: linear-gradient(135deg, #ff5c5c, #ff4081);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: 0.5px;
}

.sidebar-menu {
  flex: 1;
  border-right: none;
  padding: 12px;
  background: transparent;
}

:deep(.ant-menu-item) {
  border-radius: 12px !important;
  margin-bottom: 8px !important;
  transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
}

:deep(.ant-menu-item:hover) {
  transform: translateX(4px);
}

:deep(.ant-menu-item-selected) {
  box-shadow: 0 4px 12px rgba(255, 92, 92, 0.15);
  font-weight: 600;
}

.main-content {
  flex: 1;
  background-color: transparent;
  overflow: auto;
  height: 100vh;
  position: relative;
}
</style>
