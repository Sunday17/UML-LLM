import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/projects',
  },
  {
    path: '/projects',
    name: 'Projects',
    component: () => import('../views/projects/index.vue'),
  },
  {
    path: '/project/:id',
    name: 'ProjectDetail',
    component: () => import('../views/projects/detail.vue'),
  },
  {
    path: '/project/:id/modules',
    name: 'ProjectModules',
    component: () => import('../views/projects/modules.vue'),
  },
  {
    path: '/modeling',
    name: 'Modeling',
    component: () => import('../views/projects/detail.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router