import * as pc from 'playcanvas';

export class PlayCanvasFlyControls {
  private camera: pc.Entity;
  private mouse: pc.Mouse;
  private keyboard: pc.Keyboard;
  public worldUp: pc.Vec3;
  public enabled: boolean = true;

  private pointerLockLookSpeed: number = 0.1;
  private lookSpeed: number = 0.1;
  private panSpeed: number = 0.00075;
  public moveSpeed: number = 0.8;
  private verticalSpeed: number = 0.4;
  private scrollSpeed: number = 0.08;

  private yaw: number = 0;
  private pitch: number = 0;

  private isPointerLocked: boolean = false;
  private canvas: HTMLCanvasElement;

  constructor(mouse: pc.Mouse, camera: pc.Entity, canvas?: HTMLCanvasElement) {
    this.camera = camera;
    this.mouse = mouse;
    this.worldUp = camera.up.clone();

    // Get canvas from parameter or try to get it from mouse
    this.canvas = canvas || (this.mouse._element as HTMLCanvasElement);
    this.keyboard = new pc.Keyboard(window);

    // Calculate initial yaw and pitch from camera's forward direction
    const forward = this.camera.forward.clone();
    // Yaw is rotation around Y axis (horizontal angle)
    this.yaw = Math.atan2(-forward.x, -forward.z) * pc.math.RAD_TO_DEG;
    // Pitch is vertical angle
    this.pitch = Math.asin(forward.y) * pc.math.RAD_TO_DEG;

    this.setupMouseEvents();
  }

  // Method to explicitly set initial orientation
  public setInitialOrientation(yaw: number, pitch: number) {
    this.yaw = yaw;
    this.pitch = pitch;
  }

  // Recalculate yaw and pitch from current camera orientation
  public recalculateOrientation() {
    const forward = this.camera.forward.clone();
    // Yaw is rotation around Y axis (horizontal angle)
    this.yaw = Math.atan2(-forward.x, -forward.z) * pc.math.RAD_TO_DEG;
    // Pitch is vertical angle
    this.pitch = Math.asin(forward.y) * pc.math.RAD_TO_DEG;
  }

  private setupMouseEvents() {
    this.mouse.on(pc.EVENT_MOUSEMOVE, this.onMouseMove, this);
    this.mouse.on(pc.EVENT_MOUSEDOWN, this.onMouseDown, this);
    this.mouse.on(pc.EVENT_MOUSEWHEEL, this.onMouseWheel, this);

    // Keyboard events
    this.keyboard.on(pc.EVENT_KEYDOWN, this.onKeyDown, this);

    // Pointer lock events
    document.addEventListener('pointerlockchange', () => {
      this.isPointerLocked = this.canvas ? document.pointerLockElement === this.canvas : false;
    });
  }

  private onMouseMove = (event: pc.MouseEvent) => {
    if (!this.enabled) return;

    // Rotate camera on mouse move (both pointer locked and dragging)
    if (this.isPointerLocked || this.mouse.isPressed(pc.MOUSEBUTTON_LEFT)) {
      // Use appropriate mouse sensitivity based on mode
      const mouseSpeed = this.isPointerLocked ? this.pointerLockLookSpeed : this.lookSpeed;
      // Invert mouse look when pointer lock is active
      const invertLook = this.isPointerLocked;
      const yawDelta = invertLook ? -event.dx * mouseSpeed : event.dx * mouseSpeed;
      const pitchDelta = invertLook ? -event.dy * mouseSpeed : event.dy * mouseSpeed;

      this.yaw += yawDelta;
      this.pitch += pitchDelta;

      // Clamp pitch
      this.pitch = pc.math.clamp(this.pitch, -90, 90);

      // Apply rotation
      const rotation = new pc.Quat();
      rotation.setFromEulerAngles(this.pitch, this.yaw, 0);
      this.camera.setRotation(rotation);
    }

    // Pan camera with middle mouse button
    if (this.mouse.isPressed(pc.MOUSEBUTTON_MIDDLE)) {
      const right = this.camera.right.clone().mulScalar(-event.dx * this.panSpeed);
      const up = this.camera.up.clone().mulScalar(event.dy * this.panSpeed);

      const position = this.camera.getPosition();
      position.add(right).add(up);
      this.camera.setPosition(position);
    }
  };

  private onMouseDown = (event: pc.MouseEvent) => {
    if (!this.enabled) return;

    // Prevent default behavior for middle mouse button
    if (event.button === pc.MOUSEBUTTON_MIDDLE) {
      event.event.preventDefault();
    }
  };

  private onMouseWheel = (event: pc.MouseEvent) => {
    if (!this.enabled) return;

    // Move camera forward/backward based on scroll direction
    const forward = this.camera.forward.clone();
    const scrollDistance = event.wheel * this.scrollSpeed;

    const position = this.camera.getPosition();
    position.add(forward.mulScalar(scrollDistance));
    this.camera.setPosition(position);

    // Prevent default scroll behavior
    event.event.preventDefault();
  };

  private onKeyDown = (event: pc.KeyboardEvent) => {
    if (!this.enabled) return;

    // Space bar for pointer lock
    if (event.key === pc.KEY_SPACE) {
      event.event?.preventDefault();
      if (this.isPointerLocked) {
        document.exitPointerLock();
      } else if (this.canvas) {
        this.canvas.requestPointerLock();
      }
    }
  };

  update(dt: number) {
    if (!this.enabled) return;

    // Keyboard movement
    const forward = this.camera.forward.clone();
    const right = this.camera.right.clone();
    const up = this.worldUp.clone();

    const movement = new pc.Vec3(0, 0, 0);

    if (this.keyboard.isPressed(pc.KEY_W)) {
      movement.add(forward.mulScalar(this.moveSpeed * dt));
    }
    if (this.keyboard.isPressed(pc.KEY_S)) {
      movement.sub(forward.mulScalar(this.moveSpeed * dt));
    }
    if (this.keyboard.isPressed(pc.KEY_A)) {
      movement.sub(right.mulScalar(this.moveSpeed * dt));
    }
    if (this.keyboard.isPressed(pc.KEY_D)) {
      movement.add(right.mulScalar(this.moveSpeed * dt));
    }
    if (this.keyboard.isPressed(pc.KEY_SHIFT)) {
      movement.add(up.mulScalar(this.verticalSpeed * dt));
    }
    if (this.keyboard.isPressed(pc.KEY_CONTROL)) {
      movement.sub(up.mulScalar(this.verticalSpeed * dt));
    }
    if (this.keyboard.isPressed(pc.KEY_Q)) {
      movement.sub(up.mulScalar(this.verticalSpeed * dt));
    }

    // Mouse movement (right click for forward movement)
    if (this.mouse.isPressed(pc.MOUSEBUTTON_RIGHT)) {
      movement.add(forward.mulScalar(this.moveSpeed * dt));
    }

    // Apply movement
    const position = this.camera.getPosition();
    position.add(movement);
    this.camera.setPosition(position);
  }

  destroy() {
    this.mouse.off(pc.EVENT_MOUSEMOVE, this.onMouseMove, this);
    this.mouse.off(pc.EVENT_MOUSEDOWN, this.onMouseDown, this);
    this.mouse.off(pc.EVENT_MOUSEWHEEL, this.onMouseWheel, this);
    this.keyboard.off(pc.EVENT_KEYDOWN, this.onKeyDown, this);

    if (this.isPointerLocked) {
      document.exitPointerLock();
    }
  }

  roll(angle: number) {
    // Apply roll rotation around forward axis
    const rotation = this.camera.getRotation();
    const rollQuat = new pc.Quat();
    rollQuat.setFromAxisAngle(this.camera.forward, angle * pc.math.RAD_TO_DEG);
    rotation.mul(rollQuat);
    this.camera.setRotation(rotation);
  }
}





