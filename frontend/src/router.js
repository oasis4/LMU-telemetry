import { createRouter, createWebHistory } from 'vue-router'
import SessionLoader from './views/SessionLoader.vue'
import SessionDashboard from './views/SessionDashboard.vue'
import CornerDetail from './views/CornerDetail.vue'
import CompareView from './views/CompareView.vue'

const routes = [
  { path: '/', name: 'sessions', component: SessionLoader },
  { path: '/session/:sessionId', name: 'dashboard', component: SessionDashboard, props: true },
  { path: '/session/:sessionId/corner/:cornerId', name: 'corner', component: CornerDetail, props: true },
  { path: '/compare', name: 'compare', component: CompareView },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
