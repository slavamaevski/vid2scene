import * as pc from 'playcanvas';

export class PlayCanvasOrbitControls {
  private camera: pc.Entity;
  private mouse: pc.Mouse;
  private touch: pc.TouchDevice;
  private app: pc.AppBase;
  private picker: pc.Picker;
  public pivotPoint: pc.Vec3;
  public enabled: boolean = true;

  private distance: number = 10;
  private yaw: number = 0;
  private pitch: number = 0;

  // Velocity for momentum
  private rotationVelocity: pc.Vec2 = new pc.Vec2(0, 0);  // (yaw, pitch) as vector
  private panVelocity: pc.Vec2 = new pc.Vec2(0, 0);  // (horizontal, vertical) pan velocity

  // Control sensitivity settings
  private rotateSpeed: number = 0.3;
  private zoomSpeed: number = 0.05;
  private panSpeed: number = 0.002;
  private panAccelerationMultiplier: number = 0.5;  // Reduced for smoother pan control

  // Momentum settings
  private damping: number = 0.87;
  private momentumAcceleration: number = 0.15;

  // Limits and thresholds
  private maxPitchAngle: number = 89.5;
  private velocityStopThreshold: number = 1e-8;  // 0.00000001 (velocity magnitude squared)
  private updateDtNormalization: number = 60;

  private lastPinchDistance: number = 0;
  private lastTouchPosition: pc.Vec2 = new pc.Vec2();
  private distanceChanged: boolean = false;  // Track if distance was modified this frame

  // Tap detection for refocus
  private touchStartTime: number = 0;
  private touchStartPosition: pc.Vec2 = new pc.Vec2();
  private tapThreshold: number = 200; // ms - max time for a tap
  private tapMoveThreshold: number = 10; // pixels - max movement for a tap

  private isDragging: boolean = false;
  private isTouching: boolean = false;
  private lastVelocityUpdateTime: number = 0;
  private lastClickTime: number = 0;  // Track click timing for double-click vs drag detection
  private clickThreshold: number = 200;  // ms - click vs drag threshold

  // Animation for pivot transition
  private isAnimating: boolean = false;
  private animationProgress: number = 0;
  private animationDuration: number = 0.75;  // seconds
  private startPivot: pc.Vec3 = new pc.Vec3();
  private targetPivot: pc.Vec3 = new pc.Vec3();
  private startYaw: number = 0;
  private targetYaw: number = 0;
  private startPitch: number = 0;
  private targetPitch: number = 0;
  private startDistance: number = 0;
  private targetDistance: number = 0;

  // Visual marker for pivot point
  private pivotMarker: pc.Entity | null = null;
  private markerFadeProgress: number = 0;
  private markerFadeDuration: number = 0.8;  // seconds for full fade cycle
  private showMarker: boolean = false;

  constructor(mouse: pc.Mouse, camera: pc.Entity, touch: pc.TouchDevice | undefined, app: pc.AppBase) {
    this.camera = camera;
    this.mouse = mouse;
    this.app = app;
    this.pivotPoint = new pc.Vec3(0, 0, 0);

    // Use provided touch device or create a new one if canvas element is available
    if (touch) {
      this.touch = touch;
    } else if (mouse._element) {
      this.touch = new pc.TouchDevice(mouse._element as HTMLCanvasElement);
    } else {
      // Fallback: create a dummy touch device (won't work but won't crash)
      this.touch = new pc.TouchDevice(document.createElement('canvas'));
    }

    // Create picker for raycast-based pivot selection
    // Initialize with default size, will resize on use
    this.picker = new pc.Picker(this.app, 256, 256, true);

    // Create visual marker for pivot point
    this.createPivotMarker();

    // Calculate initial orbit parameters from camera position relative to pivot
    const camPos = this.camera.getPosition();
    const pivotToCam = new pc.Vec3();
    pivotToCam.sub2(camPos, this.pivotPoint);

    this.distance = pivotToCam.length();

    // Calculate yaw and pitch from the vector pointing from pivot to camera
    // This ensures the initial orientation matches the actual camera-pivot relationship
    this.yaw = Math.atan2(pivotToCam.x, pivotToCam.z) * pc.math.RAD_TO_DEG;
    const horizontalDist = Math.sqrt(pivotToCam.x * pivotToCam.x + pivotToCam.z * pivotToCam.z);
    this.pitch = Math.atan2(pivotToCam.y, horizontalDist) * pc.math.RAD_TO_DEG;

    this.setupMouseEvents();
    this.setupTouchEvents();
  }

  private createPivotMarker() {
    // Get the overlay layer (should be created in App.svelte)
    const overlayLayer = this.app.scene.layers.getLayerByName('Overlay');
    if (!overlayLayer) {
      console.error('Overlay layer not found! Make sure it is created in App.svelte');
      return;
    }

    // Create a billboard circle marker using a canvas-generated texture
    this.pivotMarker = new pc.Entity('pivotMarker');

    // Create a canvas to draw the circle ring
    const canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 128;
    const ctx = canvas.getContext('2d')!;

    // Draw a white circle ring
    ctx.clearRect(0, 0, 128, 128);
    ctx.strokeStyle = 'white';
    ctx.lineWidth = 6;  // Medium thickness
    ctx.beginPath();
    ctx.arc(64, 64, 48, 0, Math.PI * 2);
    ctx.stroke();

    // Create texture from canvas
    const texture = new pc.Texture(this.app.graphicsDevice, {
      width: canvas.width,
      height: canvas.height,
      format: pc.PIXELFORMAT_R8_G8_B8_A8,
      mipmaps: false
    });

    // Set the canvas as the texture source
    texture.setSource(canvas);
    texture.upload();

    // Create material
    const material = new pc.StandardMaterial();
    material.emissive = new pc.Color(1, 1, 1);
    material.emissiveMap = texture;
    material.opacityMap = texture;
    material.opacity = 0;  // Start invisible
    material.blendType = pc.BLEND_NORMAL;
    material.depthTest = false;
    material.depthWrite = false;
    material.cull = pc.CULLFACE_NONE;
    material.useLighting = false;
    material.update();

    // Add render component with a plane
    this.pivotMarker.addComponent('render', {
      type: 'plane',
      material: material,
      castShadows: false,
      receiveShadows: false,
      layers: [overlayLayer.id]
    });

    // Set scale (smaller)
    this.pivotMarker.setLocalScale(0.3, 0.3, 0.3);

    // Add to scene (start disabled)
    this.app.root.addChild(this.pivotMarker);
    this.pivotMarker.enabled = false;
  }

  private setupMouseEvents() {
    this.mouse.on(pc.EVENT_MOUSEMOVE, this.onMouseMove, this);
    this.mouse.on(pc.EVENT_MOUSEWHEEL, this.onMouseWheel, this);
    this.mouse.on(pc.EVENT_MOUSEDOWN, this.onMouseDown, this);
    this.mouse.on(pc.EVENT_MOUSEUP, this.onMouseUp, this);
  }

  private setupTouchEvents() {
    this.touch.on(pc.EVENT_TOUCHMOVE, this.onTouchMove, this);
    this.touch.on(pc.EVENT_TOUCHSTART, this.onTouchStart, this);
    this.touch.on(pc.EVENT_TOUCHEND, this.onTouchEnd, this);
  }

  private onMouseDown = (event: pc.MouseEvent) => {
    if (!this.enabled) return;

    // Only handle if click is on canvas
    const target = event.event?.target as HTMLElement;
    if (!target || target.tagName !== 'CANVAS') return;

    if (event.button === pc.MOUSEBUTTON_LEFT) {
      this.isDragging = true;
      this.lastClickTime = performance.now();

      // If animation is active, cancel it and keep current values
      if (this.isAnimating) {
        this.isAnimating = false;
        // Keep current yaw/pitch/distance values (no changes needed)
      }

      // Don't clear momentum - let it accumulate for momentum-based control
    }
  };

  private onMouseUp = (event: pc.MouseEvent) => {
    if (!this.enabled) return;

    if (event.button === pc.MOUSEBUTTON_LEFT) {
      const clickDuration = performance.now() - this.lastClickTime;

      // If it was a quick click (not a drag), try to focus on clicked point
      // Only handle focus if the click was on the canvas element (not UI)
      const target = event.event?.target as HTMLElement;
      const isCanvasClick = target && target.tagName === 'CANVAS';

      if (clickDuration < this.clickThreshold && this.rotationVelocity.lengthSq() < 0.01 && isCanvasClick) {
        this.handleFocusClick(event);
      }

      this.isDragging = false;
      // Momentum continues after release
    }
  };

  private onMouseMove = (event: pc.MouseEvent) => {
    if (!this.enabled) return;

    // Only handle if on canvas
    const target = event.event?.target as HTMLElement;
    if (!target || target.tagName !== 'CANVAS') return;

    // Left click - orbit (add to rotation velocity)
    if (this.mouse.isPressed(pc.MOUSEBUTTON_LEFT)) {
      const yawAccel = -event.dx * this.rotateSpeed * this.momentumAcceleration;
      const pitchAccel = event.dy * this.rotateSpeed * this.momentumAcceleration;  // Inverted Y

      // Add to velocity for momentum-based control
      this.rotationVelocity.x += yawAccel;
      this.rotationVelocity.y += pitchAccel;
      this.lastVelocityUpdateTime = performance.now();
    }

    // Right click or middle click - pan (add to pan velocity)
    if (this.mouse.isPressed(pc.MOUSEBUTTON_RIGHT) || this.mouse.isPressed(pc.MOUSEBUTTON_MIDDLE)) {
      const panAccel = this.momentumAcceleration * this.panAccelerationMultiplier;
      this.panVelocity.x += -event.dx * this.panSpeed * this.distance * panAccel;
      this.panVelocity.y += event.dy * this.panSpeed * this.distance * panAccel;
    }
  };

  private onMouseWheel = (event: pc.MouseEvent) => {
    if (!this.enabled) return;

    // Direct zoom without momentum (inverted direction)
    const zoomAmount = -event.wheel * this.distance * this.zoomSpeed;

    // Disable zoom during animation (animation keeps camera position fixed)
    if (this.isAnimating) {
      return;
    }

    // Normal zoom
    this.distance += zoomAmount;
    this.distance = pc.math.clamp(this.distance, 0.1, 1000);
    // Mark that distance changed - will update camera in update loop
    this.distanceChanged = true;
  };

  private onTouchStart = (event: pc.TouchEvent) => {
    // Prevent default browser behavior (page zoom, scroll, etc.)
    if (event.event) {
      event.event.preventDefault();
    }

    // Respect enabled state
    if (!this.enabled) return;

    this.isTouching = true;

    if (event.touches.length === 2) {
      const dx = event.touches[0].x - event.touches[1].x;
      const dy = event.touches[0].y - event.touches[1].y;
      this.lastPinchDistance = Math.sqrt(dx * dx + dy * dy);

      // Initialize lastTouchPosition to center of two fingers for pan tracking
      const centerX = (event.touches[0].x + event.touches[1].x) / 2;
      const centerY = (event.touches[0].y + event.touches[1].y) / 2;
      this.lastTouchPosition.set(centerX, centerY);
    } else if (event.touches.length === 1) {
      // Record touch start for tap detection
      this.touchStartTime = performance.now();
      this.touchStartPosition.set(event.touches[0].x, event.touches[0].y);

      this.lastTouchPosition.set(event.touches[0].x, event.touches[0].y);
      // Don't clear momentum - let it accumulate
    }
  };

  private onTouchEnd = (event: pc.TouchEvent) => {
    // Prevent default browser behavior
    if (event.event) {
      event.event.preventDefault();
    }

    // Respect enabled state
    if (!this.enabled) return;

    if (event.touches.length === 0) {
      // Check if this was a tap (quick touch without much movement)
      if (this.touchStartTime > 0) {
        const touchDuration = performance.now() - this.touchStartTime;
        const touchEndPos = new pc.Vec2(
          event.event?.changedTouches[0]?.clientX || this.touchStartPosition.x,
          event.event?.changedTouches[0]?.clientY || this.touchStartPosition.y
        );
        const touchMovement = this.touchStartPosition.distance(touchEndPos);

        // If it was a quick tap without much movement, treat it as a refocus click
        if (touchDuration < this.tapThreshold && touchMovement < this.tapMoveThreshold && this.rotationVelocity.lengthSq() < 0.01) {
          // Create a mock mouse event for handleFocusClick
          const mockEvent = {
            x: this.touchStartPosition.x,
            y: this.touchStartPosition.y,
            button: pc.MOUSEBUTTON_LEFT,
            dx: 0,
            dy: 0,
            event: event.event as any,
            element: event.event?.target as HTMLElement,
            ctrlKey: false,
            altKey: false,
            shiftKey: false,
            metaKey: false,
            wheelDelta: 0,
            buttons: 0,
          } as unknown as pc.MouseEvent;

          this.handleFocusClick(mockEvent);
        }

        this.touchStartTime = 0;
      }

      this.isTouching = false;
      // Momentum continues after release
    } else if (event.touches.length === 1) {
      // Transitioning from 2 fingers to 1 finger
      // Reset lastTouchPosition to prevent burst orbit
      this.lastTouchPosition.set(event.touches[0].x, event.touches[0].y);
    }
  };

  private onTouchMove = (event: pc.TouchEvent) => {
    if (!this.enabled) return;

    // Prevent default browser behavior (page zoom, scroll, etc.)
    if (event.event) {
      event.event.preventDefault();
    }

    if (event.touches.length === 2) {
      // Pinch to zoom (direct control, no momentum for zoom)
      const dx = event.touches[0].x - event.touches[1].x;
      const dy = event.touches[0].y - event.touches[1].y;
      const currentDistance = Math.sqrt(dx * dx + dy * dy);

      if (this.lastPinchDistance > 0) {
        const scale = currentDistance / this.lastPinchDistance;
        const distanceDelta = this.distance * (1.0 - scale);

        if (this.isAnimating) {
          // During animation, update all distances (inverted for intuitive pinch)
          this.distance += distanceDelta;
          this.distance = pc.math.clamp(this.distance, 0.1, 1000);

          this.targetDistance += distanceDelta;
          this.targetDistance = pc.math.clamp(this.targetDistance, 0.1, 1000);

          this.startDistance += distanceDelta;
          this.startDistance = pc.math.clamp(this.startDistance, 0.1, 1000);

          // Camera position will be updated by animation loop
        } else {
          // Normal pinch zoom when not animating (inverted for intuitive pinch)
          this.distance += distanceDelta;
          this.distance = pc.math.clamp(this.distance, 0.1, 1000);
          // Mark that distance changed - will update camera in update loop
          this.distanceChanged = true;
        }
      }

      this.lastPinchDistance = currentDistance;

      // Two finger pan (use same momentum logic as mouse right-click pan)
      const centerX = (event.touches[0].x + event.touches[1].x) / 2;
      const centerY = (event.touches[0].y + event.touches[1].y) / 2;
      const deltaX = centerX - this.lastTouchPosition.x;
      const deltaY = centerY - this.lastTouchPosition.y;

      // Use same acceleration as mouse pan
      const panAccel = this.momentumAcceleration * this.panAccelerationMultiplier;
      this.panVelocity.x += -deltaX * this.panSpeed * this.distance * panAccel;
      this.panVelocity.y += deltaY * this.panSpeed * this.distance * panAccel;

      this.lastTouchPosition.set(centerX, centerY);
    } else if (event.touches.length === 1) {
      // One finger orbit (add to velocity)
      const deltaX = event.touches[0].x - this.lastTouchPosition.x;
      const deltaY = event.touches[0].y - this.lastTouchPosition.y;

      const yawAccel = -deltaX * this.rotateSpeed * this.momentumAcceleration;
      const pitchAccel = deltaY * this.rotateSpeed * this.momentumAcceleration;

      // Add to velocity for momentum-based control
      this.rotationVelocity.x += yawAccel;
      this.rotationVelocity.y += pitchAccel;
      this.lastVelocityUpdateTime = performance.now();

      this.lastTouchPosition.set(event.touches[0].x, event.touches[0].y);
    }
  };

  private updateCameraPosition() {
    // Calculate camera position from orbit parameters
    const pitchRad = this.pitch * pc.math.DEG_TO_RAD;
    const yawRad = this.yaw * pc.math.DEG_TO_RAD;

    const offset = new pc.Vec3(
      Math.sin(yawRad) * Math.cos(pitchRad),
      Math.sin(pitchRad),
      Math.cos(yawRad) * Math.cos(pitchRad)
    );

    offset.mulScalar(this.distance);

    const newPosition = this.pivotPoint.clone().add(offset);
    this.camera.setPosition(newPosition);
    this.camera.lookAt(this.pivotPoint);
  }

  update(dt: number) {
    if (!this.enabled) return;

    // Handle pivot marker fade animation
    if (this.showMarker && this.pivotMarker) {
      this.markerFadeProgress += dt / this.markerFadeDuration;

      if (this.markerFadeProgress >= 1.0) {
        // Fade complete, hide marker
        this.showMarker = false;
        this.pivotMarker.enabled = false;
        this.markerFadeProgress = 0;
      } else {
        // Calculate opacity with fade in and fade out
        // Fade in quickly (first 20%), stay visible (middle 60%), fade out (last 20%)
        let opacity = 0;
        if (this.markerFadeProgress < 0.2) {
          // Fade in
          opacity = this.markerFadeProgress / 0.2;
        } else if (this.markerFadeProgress < 0.8) {
          // Stay visible
          opacity = 1;
        } else {
          // Fade out
          opacity = (1.0 - this.markerFadeProgress) / 0.2;
        }

        // Make the plane always face the camera (billboard effect)
        // Copy camera's rotation and add 90 degree offset for plane orientation
        this.pivotMarker.setRotation(this.camera.getRotation());
        this.pivotMarker.rotateLocal(90, 0, 0);  // Planes are horizontal by default, rotate to face forward

        // Scale marker based on distance to camera so it appears constant size on screen
        const markerPos = this.pivotMarker.getPosition();
        const camPos = this.camera.getPosition();
        const distanceToCamera = markerPos.distance(camPos);
        const finalScale = distanceToCamera * 0.075;  // Scale proportional to distance
        this.pivotMarker.setLocalScale(finalScale, finalScale, finalScale);

        // Update marker opacity
        const material = this.pivotMarker.render?.meshInstances[0]?.material as pc.StandardMaterial;
        if (material) {
          material.opacity = opacity;
          material.update();
        }
      }
    }

    // Handle pivot transition animation
    if (this.isAnimating) {
      // Continue animation
      this.animationProgress += dt / this.animationDuration;

      if (this.animationProgress >= 1.0) {
        // Animation complete
        this.animationProgress = 1.0;
        this.isAnimating = false;
      }

      // Use ease-out cubic for smooth deceleration
      const t = this.animationProgress;
      const eased = 1 - Math.pow(1 - t, 3);

      // Interpolate pivot point
      this.pivotPoint.lerp(this.startPivot, this.targetPivot, eased);

      // Recalculate yaw/pitch/distance to keep camera in same position
      // pointing at the (now moved) pivot
      const camPos = this.camera.getPosition();
      const pivotToCam = new pc.Vec3();
      pivotToCam.sub2(camPos, this.pivotPoint);

      // Update distance
      this.distance = pivotToCam.length();

      // Update yaw and pitch
      this.yaw = Math.atan2(pivotToCam.x, pivotToCam.z) * pc.math.RAD_TO_DEG;
      const horizontalDist = Math.sqrt(pivotToCam.x * pivotToCam.x + pivotToCam.z * pivotToCam.z);
      this.pitch = Math.atan2(pivotToCam.y, horizontalDist) * pc.math.RAD_TO_DEG;

      // Update camera to look at new pivot (position stays the same)
      this.camera.lookAt(this.pivotPoint);
    }

    // Apply momentum continuously (frame-rate independent)
    const dtFactor = dt * this.updateDtNormalization;

    // Apply rotation velocities
    this.yaw += this.rotationVelocity.x * dtFactor;
    this.pitch += this.rotationVelocity.y * dtFactor;

    // Clamp pitch
    this.pitch = pc.math.clamp(this.pitch, -this.maxPitchAngle, this.maxPitchAngle);

    // Apply pan velocities - move both pivot AND camera together
    let panMovement: pc.Vec3 | null = null;
    if (this.panVelocity.lengthSq() > 0) {
      const right = this.camera.right.clone().mulScalar(this.panVelocity.x * dtFactor);
      const up = this.camera.up.clone().mulScalar(this.panVelocity.y * dtFactor);
      panMovement = new pc.Vec3();
      panMovement.add(right).add(up);

      // Move pivot
      this.pivotPoint.add(panMovement);

      // Move camera by the same amount so it stays in the same orbital position
      const camPos = this.camera.getPosition();
      camPos.add(panMovement);
      this.camera.setPosition(camPos);
    }

    // Apply damping to all velocities (frame-rate independent)
    const dampingFactor = Math.pow(this.damping, dtFactor);
    this.rotationVelocity.mulScalar(dampingFactor);
    this.panVelocity.mulScalar(dampingFactor);

    // Stop velocities when magnitude is very small
    if (this.rotationVelocity.lengthSq() < this.velocityStopThreshold) {
      this.rotationVelocity.set(0, 0);
    }
    if (this.panVelocity.lengthSq() < this.velocityStopThreshold) {
      this.panVelocity.set(0, 0);
    }

    // Update camera position if there's rotation velocity OR if distance changed (zoom)
    // Don't update if only pan happened (pan moves camera and pivot together)
    if (this.rotationVelocity.lengthSq() > 0 || this.distanceChanged) {
      this.updateCameraPosition();
      this.distanceChanged = false;  // Reset flag
    }
  }

  focusOnPoint(point: pc.Vec3) {
    this.pivotPoint.copy(point);
    this.updateCameraPosition();
  }

  resetMomentum() {
    // Clear all momentum velocities
    this.rotationVelocity.set(0, 0);
    this.panVelocity.set(0, 0);
  }

  recalculateFromCameraAndPivot() {
    // Recalculate yaw, pitch, and distance based on current camera position and pivot point
    // This should be called when the pivot point changes or when switching control modes
    const camPos = this.camera.getPosition();
    const pivotToCam = new pc.Vec3();
    pivotToCam.sub2(camPos, this.pivotPoint);

    this.distance = pivotToCam.length();

    // Calculate yaw and pitch from the vector pointing from pivot to camera
    this.yaw = Math.atan2(pivotToCam.x, pivotToCam.z) * pc.math.RAD_TO_DEG;
    const horizontalDist = Math.sqrt(pivotToCam.x * pivotToCam.x + pivotToCam.z * pivotToCam.z);
    this.pitch = Math.atan2(pivotToCam.y, horizontalDist) * pc.math.RAD_TO_DEG;

    // Clear momentum
    this.resetMomentum();
  }

  private handleFocusClick(event: pc.MouseEvent) {
    // Get canvas from the event target
    const canvas = event.event?.target as HTMLCanvasElement;
    if (!canvas || !this.camera.camera) return;

    // Use picker to find the actual world point at the clicked location
    const pickerScale = 0.25;

    // Resize picker to match current canvas size (scaled down for performance)
    this.picker.resize(canvas.clientWidth * pickerScale, canvas.clientHeight * pickerScale);

    // Prepare picker with the scene - use world layer (standard PlayCanvas layer)
    const worldLayer = this.app.scene.layers.getLayerById(pc.LAYERID_WORLD);
    if (!worldLayer) {
      console.error('Could not find world layer');
      return;
    }

    this.picker.prepare(this.camera.camera, this.app.scene, [worldLayer]);

    // Get scaled mouse coordinates
    const centerX = event.x * pickerScale;
    const centerY = event.y * pickerScale;

    // Sample multiple points in a small area around the click to find the closest one
    const sampleRadius = 3;  // pixels to sample around click
    const samplePoints: Array<{ x: number, y: number }> = [];

    // Create a grid of sample points
    for (let dx = -sampleRadius; dx <= sampleRadius; dx += sampleRadius) {
      for (let dy = -sampleRadius; dy <= sampleRadius; dy += sampleRadius) {
        samplePoints.push({ x: centerX + dx, y: centerY + dy });
      }
    }

    // Pick all sample points and find the closest valid one
    const pickPromises = samplePoints.map(point =>
      this.picker.getWorldPointAsync(point.x, point.y)
        .then(worldPoint => ({ worldPoint, point }))
        .catch(() => ({ worldPoint: null, point }))
    );

    Promise.all(pickPromises).then(results => {
      const camPos = this.camera.getPosition();

      // Define minimum distance to avoid picking too close
      const minDistance = this.distance * 0.2;  // Not too close (20% of current)

      // Filter valid points and find the closest one
      let closestPoint: pc.Vec3 | null = null;
      let closestDistance = Infinity;

      for (const result of results) {
        if (result.worldPoint) {
          const dist = result.worldPoint.distance(camPos);

          // Check if above minimum distance
          if (dist >= minDistance) {
            if (dist < closestDistance) {
              closestDistance = dist;
              closestPoint = result.worldPoint;
            }
          }
        }
      }

      if (closestPoint) {
        this.animatePivotTransition(closestPoint);
      } else {
        console.log('No valid points found (all too close)');
      }
    });
  }

  private animatePivotTransition(targetPivot: pc.Vec3) {
    const camPos = this.camera.getPosition();

    // Clear any existing momentum to prevent residual movement after animation
    this.resetMomentum();

    // Calculate the vector from new pivot to camera
    const pivotToCam = new pc.Vec3();
    pivotToCam.sub2(camPos, targetPivot);

    // Calculate new distance (from camera to new pivot)
    const newDistance = pivotToCam.length();

    // Calculate new yaw and pitch to point from camera position toward new pivot
    // Yaw is rotation around Y axis
    const newYaw = Math.atan2(pivotToCam.x, pivotToCam.z) * pc.math.RAD_TO_DEG;

    // Pitch is angle from horizontal plane
    const horizontalDist = Math.sqrt(pivotToCam.x * pivotToCam.x + pivotToCam.z * pivotToCam.z);
    const newPitch = Math.atan2(pivotToCam.y, horizontalDist) * pc.math.RAD_TO_DEG;

    // Store current state as start
    this.startPivot.copy(this.pivotPoint);
    this.startYaw = this.yaw;
    this.startPitch = this.pitch;
    this.startDistance = this.distance;

    // Store target state
    this.targetPivot.copy(targetPivot);
    this.targetPitch = pc.math.clamp(newPitch, -this.maxPitchAngle, this.maxPitchAngle);
    this.targetDistance = pc.math.clamp(newDistance, 0.1, 1000);

    // Handle angle wrapping for yaw - take shortest path
    this.targetYaw = newYaw;
    let yawDiff = this.targetYaw - this.startYaw;

    // Normalize to -180 to 180 range
    while (yawDiff > 180) yawDiff -= 360;
    while (yawDiff < -180) yawDiff += 360;

    // Adjust target yaw to take shortest path
    this.targetYaw = this.startYaw + yawDiff;

    // Show marker at new pivot point
    if (this.pivotMarker) {
      this.pivotMarker.setPosition(targetPivot);
      this.pivotMarker.enabled = true;
      this.showMarker = true;
      this.markerFadeProgress = 0;
    }

    // Start animation
    this.isAnimating = true;
    this.animationProgress = 0;
  }

  raycastAndSetPivot(showMarker: boolean = true): Promise<boolean> {
    return new Promise((resolve) => {
      if (!this.camera.camera) {
        resolve(false);
        return;
      }

      // Create a picker for raycasting
      const pickerScale = 0.25;
      const width = this.app.graphicsDevice.width;
      const height = this.app.graphicsDevice.height;
      const picker = new pc.Picker(this.app, width * pickerScale, height * pickerScale, true);

      // Prepare picker with the world layer
      const worldLayer = this.app.scene.layers.getLayerById(pc.LAYERID_WORLD);
      if (!worldLayer) {
        console.error('Could not find world layer for raycasting');
        resolve(false);
        return;
      }

      picker.prepare(this.camera.camera, this.app.scene, [worldLayer]);

      // Define raycast points in a 3x3 grid pattern
      const centerX = width * 0.5 * pickerScale;
      const centerY = height * 0.5 * pickerScale;
      const offset = width * 0.15 * pickerScale; // 15% offset from center

      const raycastPoints = [
        { x: centerX, y: centerY },           // Center
        { x: centerX - offset, y: centerY },  // Left
        { x: centerX + offset, y: centerY },  // Right
        { x: centerX, y: centerY - offset },  // Top
        { x: centerX, y: centerY + offset },  // Bottom
        { x: centerX - offset, y: centerY - offset }, // Top-left
        { x: centerX + offset, y: centerY - offset }, // Top-right
        { x: centerX - offset, y: centerY + offset }, // Bottom-left
        { x: centerX + offset, y: centerY + offset }, // Bottom-right
      ];

      // Perform all raycasts
      const raycastPromises = raycastPoints.map(point =>
        picker.getWorldPointAsync(point.x, point.y).catch(() => null)
      );

      Promise.all(raycastPromises).then((results) => {
        const camPos = this.camera.getPosition();
        let closestDistance = Infinity;

        // Find the closest valid distance from all hits
        for (const worldPoint of results) {
          if (worldPoint) {
            const distance = worldPoint.distance(camPos);

            // Only consider points at reasonable distances
            if (distance > 0.5 && distance < 1000 && distance < closestDistance) {
              closestDistance = distance;
            }
          }
        }

        if (closestDistance !== Infinity) {
          // Project the closest distance along the center forward direction
          const forward = this.camera.forward.clone();
          const pivotPoint = camPos.clone().add(forward.mulScalar(closestDistance));

          this.pivotPoint.copy(pivotPoint);
          this.recalculateFromCameraAndPivot();

          // Show marker if requested
          if (showMarker && this.pivotMarker) {
            this.pivotMarker.setPosition(pivotPoint);
            this.pivotMarker.enabled = true;
            this.showMarker = true;
            this.markerFadeProgress = 0;
          }

          console.log('Set pivot to closest distance projected from center:', closestDistance);
          resolve(true);
        } else {
          // No valid hits
          console.log('All raycasts missed or were out of range');
          resolve(false);
        }
      }).catch((error) => {
        console.warn('Raycast error:', error);
        resolve(false);
      });
    });
  }

  destroy() {
    this.mouse.off(pc.EVENT_MOUSEMOVE, this.onMouseMove, this);
    this.mouse.off(pc.EVENT_MOUSEWHEEL, this.onMouseWheel, this);
    this.mouse.off(pc.EVENT_MOUSEDOWN, this.onMouseDown, this);
    this.mouse.off(pc.EVENT_MOUSEUP, this.onMouseUp, this);
    this.touch.off(pc.EVENT_TOUCHMOVE, this.onTouchMove, this);
    this.touch.off(pc.EVENT_TOUCHSTART, this.onTouchStart, this);
    this.touch.off(pc.EVENT_TOUCHEND, this.onTouchEnd, this);

    // Clean up pivot marker
    if (this.pivotMarker) {
      this.pivotMarker.destroy();
      this.pivotMarker = null;
    }
  }
}





