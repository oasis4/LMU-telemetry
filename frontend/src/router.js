import { createRouter, createWebHistory } from 'vue-router'

import CompareView from './views/CompareView.vue'
import SessionsView from './views/SessionsView.vue'

// The comparison is the landing page. It is what the tool is for, and it was
// the view that did not work.
const routes = [
  { path: '/', name: 'compare', component: CompareView },
  { path: '/recordings', name: 'sessions', component: SessionsView },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
