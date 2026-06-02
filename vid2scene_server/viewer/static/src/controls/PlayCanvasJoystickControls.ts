import * as pc from 'playcanvas';
import nipplejs from 'nipplejs';

export class PlayCanvasJoystickControls {
  private camera: pc.Entity;
  private movementManager: nipplejs.JoystickManager;
  private rotationManager: nipplejs.JoystickManager;
  public moveSpeed: number = 0.8; // Units per second
  private rotationSpeed: number = 60; // Degrees per second

  public enabled: boolean = true;

  // Touch handling
  private canvas: HTMLCanvasElement | null = null;
  private rotationTouchSensitivity: number = 0.15; // Degrees per pixel
  public touchPanSpeed: number = 0.003;
  public pinchZoomSpeed: number = 0.005;

  // Rotation state (same approach as FlyControls)
  private yaw: number = 0;
  private pitch: number = 0;

  // Current input state
  private currentMovement: { forward: number; right: number } = { forward: 0, right: 0 };
  private currentRotationInput: { yaw: number; pitch: number } = { yaw: 0, pitch: 0 };

  // Touch state
  private isTouchDragging: boolean = false;
  private lastTouchPosition: pc.Vec2 = new pc.Vec2();
  private isPanGesture: boolean = false;
  private initialPanPositions: [pc.Vec2, pc.Vec2] = [new pc.Vec2(), new pc.Vec2()];
  private isPinching: boolean = false;
  private initialPinchDistance: number = 0;

  constructor(
    camera: pc.Entity,
    movementManager: nipplejs.JoystickManager,
    rotationManager: nipplejs.JoystickManager
  ) {
    this.camera = camera;
    this.movementManager = movementManager;
    this.rotationManager = rotationManager;

    // Try to get canvas element for touch events
    this.canvas = document.querySelector('#playcanvas-canvas') as HTMLCanvasElement;

    // Initialize yaw and pitch from camera's current orientation
    this.syncWithCamera();

    this.setupMovementControls();
    this.setupRotationControls();
    this.setupTouchControls();
  }

  /**
   * Syncs internal yaw/pitch state with the actual camera orientation.
   * Call this whenever control is returned to this class (e.g. on touch start).
   */
  public syncWithCamera() {
    const forward = this.camera.forward.clone();
    this.yaw = Math.atan2(-forward.x, -forward.z) * pc.math.RAD_TO_DEG;
    this.pitch = Math.asin(forward.y) * pc.math.RAD_TO_DEG;
  }

  private setupMovementControls() {
    this.movementManager.on('move', (evt, data) => {
      if (!this.enabled) return;
      const force = Math.min(data.force, 1);
      const angle = data.angle.radian;

      // Joystick X-axis (left/right) = strafe right
      // Joystick Y-axis (up/down) = move forward
      this.currentMovement.right = Math.cos(angle) * force * this.moveSpeed;
      this.currentMovement.forward = Math.sin(angle) * force * this.moveSpeed;
    });

    this.movementManager.on('end', () => {
      this.currentMovement.right = 0;
      this.currentMovement.forward = 0;
    });
  }

  private setupRotationControls() {
    this.rotationManager.on('start', () => {
      if (!this.enabled) return;
      this.syncWithCamera();
    });

    this.rotationManager.on('move', (evt, data) => {
      if (!this.enabled) return;
      const force = Math.min(data.force, 1);
      const angle = data.angle.radian;

      // Joystick X-axis (left/right) = yaw rotation
      // Joystick Y-axis (up/down) = pitch rotation
      // INVERTED to match intuitive controls
      this.currentRotationInput.yaw = -Math.cos(angle) * force * this.rotationSpeed;
      this.currentRotationInput.pitch = Math.sin(angle) * force * this.rotationSpeed;
    });

    this.rotationManager.on('end', () => {
      this.currentRotationInput.yaw = 0;
      this.currentRotationInput.pitch = 0;
    });
  }

  private setupTouchControls() {
    if (!this.canvas) return;

    this.canvas.addEventListener('touchstart', this.onTouchStart, { passive: false });
    this.canvas.addEventListener('touchmove', this.onTouchMove, { passive: false });
    this.canvas.addEventListener('touchend', this.onTouchEnd, { passive: false });
  }

  private onTouchStart = (event: TouchEvent) => {
    if (!this.enabled) return;

    if (event.touches.length === 1) {
      // Single touch for rotation - sync state first to prevent jumping
      this.syncWithCamera();

      // Single touch for rotation

      this.isTouchDragging = true;
      this.lastTouchPosition.set(event.touches[0].clientX, event.touches[0].clientY);
    } else if (event.touches.length === 2) {
      // Two-finger touch for panning and pinch zoom
      const touch1 = event.touches[0];
      const touch2 = event.touches[1];
      this.isPanGesture = true;

      // Initialize pan positions
      this.initialPanPositions = [
        new pc.Vec2(touch1.clientX, touch1.clientY),
        new pc.Vec2(touch2.clientX, touch2.clientY)
      ];

      // Initialize pinch zoom
      const dx = touch2.clientX - touch1.clientX;
      const dy = touch2.clientY - touch1.clientY;
      this.initialPinchDistance = Math.sqrt(dx * dx + dy * dy);
      this.isPinching = true;
    }
  };

  private onTouchMove = (event: TouchEvent) => {
    event.preventDefault(); // Prevent page scrolling
    if (!this.enabled) return;

    if (this.isPanGesture && event.touches.length === 2) {
      const touch1 = event.touches[0];
      const touch2 = event.touches[1];
      const currentPanPositions: [pc.Vec2, pc.Vec2] = [
        new pc.Vec2(touch1.clientX, touch1.clientY),
        new pc.Vec2(touch2.clientX, touch2.clientY)
      ];

      // Calculate the average movement for panning
      const delta1 = new pc.Vec2().sub2(currentPanPositions[0], this.initialPanPositions[0]);
      const delta2 = new pc.Vec2().sub2(currentPanPositions[1], this.initialPanPositions[1]);
      const averageDelta = new pc.Vec2().add2(delta1, delta2).mulScalar(0.5);

      // Update initial pan positions for the next move event
      this.initialPanPositions = currentPanPositions;

      // Convert screen delta to world delta and apply panning
      const panOffsetX = -averageDelta.x * this.touchPanSpeed;
      const panOffsetY = averageDelta.y * this.touchPanSpeed;

      const right = this.camera.right.clone();
      const up = this.camera.up.clone();
      right.y = 0;
      right.normalize();
      up.set(0, 1, 0); // Always pan vertically

      const panMovement = new pc.Vec3();
      panMovement.add(right.mulScalar(panOffsetX));
      panMovement.add(up.mulScalar(panOffsetY));

      const pos = this.camera.getPosition();
      pos.add(panMovement);
      this.camera.setPosition(pos);

      // Handle pinch zoom
      if (this.isPinching) {
        const dx = currentPanPositions[1].x - currentPanPositions[0].x;
        const dy = currentPanPositions[1].y - currentPanPositions[0].y;
        const currentDistance = Math.sqrt(dx * dx + dy * dy);
        const pinchDelta = currentDistance - this.initialPinchDistance;
        this.initialPinchDistance = currentDistance;

        // Apply zoom based on pinch delta (move forward/backward along camera direction)
        const zoomMovement = pinchDelta * this.pinchZoomSpeed;
        const forward = this.camera.forward.clone();

        const zoomPos = this.camera.getPosition();
        zoomPos.add(forward.mulScalar(zoomMovement));
        this.camera.setPosition(zoomPos);
      }
    } else if (this.isTouchDragging && event.touches.length === 1) {
      // Single touch for rotation
      const touch = event.touches[0];
      const currentPosition = new pc.Vec2(touch.clientX, touch.clientY);
      const delta = new pc.Vec2().sub2(currentPosition, this.lastTouchPosition);
      this.lastTouchPosition.copy(currentPosition);

      // Apply rotation based on touch movement
      this.yaw += delta.x * this.rotationTouchSensitivity;
      this.pitch += delta.y * this.rotationTouchSensitivity;

      // Clamp pitch
      this.pitch = pc.math.clamp(this.pitch, -89, 89);

      // Apply rotation
      const rotation = new pc.Quat();
      rotation.setFromEulerAngles(this.pitch, this.yaw, 0);
      this.camera.setRotation(rotation);
    }
  };

  private onTouchEnd = (event: TouchEvent) => {
    if (this.isPanGesture && event.touches.length < 2) {
      this.isPanGesture = false;
      this.isPinching = false;

      // If one finger remains, initiate touch dragging for rotation
      if (event.touches.length === 1) {
        this.isTouchDragging = true;
        const remainingTouch = event.touches[0];
        this.lastTouchPosition.set(remainingTouch.clientX, remainingTouch.clientY);
      }
    }
    if (this.isTouchDragging && event.touches.length === 0) {
      this.isTouchDragging = false;
    }
  };

  /**
   * Update method to be called each frame with delta time
   * @param deltaTime Time since last frame in seconds
   */
  update(deltaTime: number) {
    // Apply rotation (using the same pattern as FlyControls)
    if (this.currentRotationInput.yaw !== 0 || this.currentRotationInput.pitch !== 0) {
      this.yaw += this.currentRotationInput.yaw * deltaTime;
      this.pitch += this.currentRotationInput.pitch * deltaTime;

      // Clamp pitch to prevent gimbal lock
      this.pitch = pc.math.clamp(this.pitch, -89, 89);

      // Apply rotation using quaternion
      const rotation = new pc.Quat();
      rotation.setFromEulerAngles(this.pitch, this.yaw, 0);
      this.camera.setRotation(rotation);
    }

    // Apply movement (in camera's local space)
    if (this.currentMovement.forward !== 0 || this.currentMovement.right !== 0) {
      // Use camera's forward and right vectors
      const forward = this.camera.forward.clone();
      const right = this.camera.right.clone();

      // Calculate movement vector
      const movement = new pc.Vec3();
      movement.add(forward.mulScalar(this.currentMovement.forward * deltaTime));
      movement.add(right.mulScalar(this.currentMovement.right * deltaTime));

      // Apply to camera position
      const pos = this.camera.getPosition();
      pos.add(movement);
      this.camera.setPosition(pos);
    }
  }

  destroy() {
    // Clean up touch event listeners
    if (this.canvas) {
      this.canvas.removeEventListener('touchstart', this.onTouchStart);
      this.canvas.removeEventListener('touchmove', this.onTouchMove);
      this.canvas.removeEventListener('touchend', this.onTouchEnd);
    }
  }
}
