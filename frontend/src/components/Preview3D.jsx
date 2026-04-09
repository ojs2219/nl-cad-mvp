import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

export default function Preview3D({ stlUrl }) {
  const mountRef = useRef(null)

  useEffect(() => {
    if (!stlUrl || !mountRef.current) return

    const container = mountRef.current
    const width = container.clientWidth || 600
    const height = container.clientHeight || 420

    // Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setSize(width, height)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.shadowMap.enabled = true
    container.appendChild(renderer.domElement)

    // Scene
    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0xf0f4f8)

    // Camera
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.01, 50000)
    camera.position.set(200, 160, 200)

    // Lights
    scene.add(new THREE.AmbientLight(0xffffff, 0.65))
    const dir1 = new THREE.DirectionalLight(0xffffff, 0.85)
    dir1.position.set(2, 4, 3)
    scene.add(dir1)
    const dir2 = new THREE.DirectionalLight(0x8899ff, 0.25)
    dir2.position.set(-2, -1, -2)
    scene.add(dir2)

    // Grid
    const grid = new THREE.GridHelper(500, 40, 0xbbbbbb, 0xdddddd)
    scene.add(grid)

    // Axes helper (small)
    scene.add(new THREE.AxesHelper(20))

    // Controls
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.06
    controls.minDistance = 1
    controls.maxDistance = 20000

    // Load STL
    const loader = new STLLoader()
    loader.load(
      stlUrl,
      (geometry) => {
        geometry.computeBoundingBox()
        const box = geometry.boundingBox
        const center = new THREE.Vector3()
        box.getCenter(center)
        // Center X/Y, place bottom at z=0
        geometry.translate(-center.x, -center.y, -box.min.z)

        const material = new THREE.MeshPhongMaterial({
          color: 0x4a90e2,
          specular: 0x444444,
          shininess: 50,
        })
        const mesh = new THREE.Mesh(geometry, material)
        mesh.castShadow = true
        scene.add(mesh)

        // Auto-fit camera
        const newBox = new THREE.Box3().setFromObject(mesh)
        const size = newBox.getSize(new THREE.Vector3())
        const maxDim = Math.max(size.x, size.y, size.z)
        const dist = maxDim * 2.2
        camera.position.set(dist, dist * 0.8, dist)
        const midZ = size.z / 2
        camera.lookAt(0, 0, midZ)
        controls.target.set(0, 0, midZ)
        controls.update()
      },
      undefined,
      (err) => console.error('STL load error:', err)
    )

    // Animation loop
    let animId
    const animate = () => {
      animId = requestAnimationFrame(animate)
      controls.update()
      renderer.render(scene, camera)
    }
    animate()

    // Resize handler
    const onResize = () => {
      if (!container) return
      const w = container.clientWidth
      const h = container.clientHeight
      if (!w || !h) return
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    }
    window.addEventListener('resize', onResize)

    return () => {
      cancelAnimationFrame(animId)
      window.removeEventListener('resize', onResize)
      controls.dispose()
      renderer.dispose()
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement)
      }
    }
  }, [stlUrl])

  return (
    <div
      ref={mountRef}
      style={{ width: '100%', height: '420px', borderRadius: '8px', overflow: 'hidden' }}
    />
  )
}
