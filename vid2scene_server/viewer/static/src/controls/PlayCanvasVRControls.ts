import * as pc from 'playcanvas';

/**
 * VR Controls for smooth locomotion using XR controller joysticks
 * Left stick: Movement (forward/back/strafe)
 * Right stick: Rotation (yaw/pitch)
 */
export class PlayCanvasVRControls {
    private app: pc.AppBase;
    private camera: pc.Entity;
    private cameraRig: pc.Entity; // Parent entity that we move
    private enabled: boolean = true;

    // Movement and rotation speeds
    private moveSpeed: number = 1; // Units per second (reduced from 2.0)
    private rotationSpeed: number = 60; // Degrees per second

    // Input sources (controllers)
    private leftController: pc.XrInputSource | null = null;
    private rightController: pc.XrInputSource | null = null;

    // Deadzone for joystick input
    private joystickDeadzone: number = 0.15;

    // First-frame VR compensation
    private targetCameraPosition: pc.Vec3 | null = null;
    private needsVRCompensation: boolean = false;
    private vrTimeElapsed: number = 0;
    private readonly VR_COMPENSATION_DELAY = 0.1; // seconds

    constructor(app: pc.AppBase, camera: pc.Entity, preVRCameraPosition: pc.Vec3, preVRCameraForward: pc.Vec3) {
        this.app = app;
        this.camera = camera;

        // Create camera rig (parent entity for VR movement)
        this.cameraRig = new pc.Entity('camera-rig');
        this.app.root.addChild(this.cameraRig);

        // Use pre-VR camera state (captured BEFORE VR started)
        const camPos = preVRCameraPosition;
        const camForward = preVRCameraForward;

        // Project camera's forward direction onto horizontal plane
        // This gives us the direction the camera was looking, ignoring pitch
        const horizontalForward = new pc.Vec3(camForward.x, 0, camForward.z);

        // Handle edge case where camera is looking straight up/down
        if (horizontalForward.lengthSq() < 0.001) {
            // Use camera's right vector to determine facing direction
            const camRight = camera.right.clone();
            horizontalForward.set(camRight.z, 0, -camRight.x); // 90 degrees from right
        }
        horizontalForward.normalize();

        // Set rig at camera's current position
        this.cameraRig.setPosition(camPos);

        // Make rig look in the horizontal direction
        const horizontalTarget = new pc.Vec3();
        horizontalTarget.add2(camPos, horizontalForward);
        this.cameraRig.lookAt(horizontalTarget);

        // Reparent camera to rig and reset to origin
        // VR will handle camera positioning based on headset tracking
        camera.reparent(this.cameraRig);
        camera.setLocalPosition(0, 0, 0);
        camera.setLocalRotation(0, 0, 0, 1);

        // Important: After reparenting and resetting, VR may have already applied headset offset
        // Check camera's actual world position and compensate if needed
        const actualCameraPos = camera.getPosition();
        if (!actualCameraPos.equals(camPos)) {
            // Camera is not where we want it - adjust rig
            const positionDelta = new pc.Vec3();
            positionDelta.sub2(camPos, actualCameraPos);
            const rigPos = this.cameraRig.getPosition();
            rigPos.add(positionDelta);
            this.cameraRig.setPosition(rigPos);

            console.log('VR headset offset detected and compensated in constructor');
            console.log('Position delta:', positionDelta.toString());
        }

        // Store target position for first-frame compensation (in case constructor compensation isn't enough)
        this.targetCameraPosition = camPos.clone();
        this.needsVRCompensation = true;

        // Set up input source listeners
        this.setupInputSources();
    }

    private setupInputSources() {
        // Listen for controller connection
        this.app.xr!.input.on('add', this.onInputSourceAdd);
        this.app.xr!.input.on('remove', this.onInputSourceRemove);

        // Check for already-connected controllers
        // Check for already-connected controllers
        const inputSources = (this.app.xr!.input as any).inputSources || [];

        // Iterate through any existing controllers
        for (let i = 0; i < inputSources.length; i++) {
            const inputSource = inputSources[i];
            if (inputSource) {
                console.log('Registering existing controller:', inputSource.handedness);
                this.onInputSourceAdd(inputSource);
            }
        }
    }

    private onInputSourceAdd = (inputSource: pc.XrInputSource) => {
        // Try to get handedness from the underlying XR input source
        const handedness = inputSource.handedness || (inputSource as any).xrInputSource?.handedness || '';

        // Only assign if handedness is available
        if (handedness === 'left') {
            this.leftController = inputSource;
        } else if (handedness === 'right') {
            this.rightController = inputSource;
        }
    };

    private onInputSourceRemove = (inputSource: pc.XrInputSource) => {
        console.log('VR input source removed:', inputSource.handedness);

        if (inputSource === this.leftController) {
            this.leftController = null;
        } else if (inputSource === this.rightController) {
            this.rightController = null;
        }
    };

    /**
     * Apply deadzone to joystick axis value
     */
    private applyDeadzone(value: number): number {
        if (Math.abs(value) < this.joystickDeadzone) {
            return 0;
        }
        // Scale the value so deadzone maps to 0 and max maps to 1
        const sign = value > 0 ? 1 : -1;
        return sign * ((Math.abs(value) - this.joystickDeadzone) / (1 - this.joystickDeadzone));
    }

    /**
     * Update VR controls - called every frame
     */
    update(dt: number) {
        if (!this.enabled || !this.app.xr!.active) return;

        // Delayed compensation for VR headset initial position/rotation
        // Wait for VR tracking to fully initialize (takes several frames)
        if (this.needsVRCompensation && this.targetCameraPosition) {
            this.vrTimeElapsed += dt;

            // Wait until 0.1 seconds has elapsed before compensating
            if (this.vrTimeElapsed >= this.VR_COMPENSATION_DELAY) {
                // By now, VR has applied initial headset tracking to the camera
                const actualCameraPos = this.camera.getPosition();
                const positionDelta = new pc.Vec3();
                positionDelta.sub2(this.targetCameraPosition, actualCameraPos);

                // ALSO compensate for headset rotation
                // Get camera's current horizontal forward (after VR applied headset rotation)
                const actualCameraForward = this.camera.forward.clone();
                const actualHorizontalForward = new pc.Vec3(actualCameraForward.x, 0, actualCameraForward.z);
                actualHorizontalForward.normalize();

                // Get rig's current horizontal forward (what we set based on pre-VR camera)
                const rigForward = this.cameraRig.forward.clone();
                const rigHorizontalForward = new pc.Vec3(rigForward.x, 0, rigForward.z);
                rigHorizontalForward.normalize();

                // Calculate yaw difference
                const dot = rigHorizontalForward.dot(actualHorizontalForward);
                const cross = new pc.Vec3();
                cross.cross(rigHorizontalForward, actualHorizontalForward);
                const headsetYawOffset = Math.atan2(cross.y, dot) * pc.math.RAD_TO_DEG;

                console.log('VR Compensation applied (Position delta:', positionDelta.length().toFixed(4), 'm, Yaw:', headsetYawOffset.toFixed(2), 'deg)');

                // Apply position compensation
                const rigPos = this.cameraRig.getPosition();
                rigPos.add(positionDelta);
                this.cameraRig.setPosition(rigPos);

                // Apply rotation compensation (counter-rotate by headset yaw)
                if (Math.abs(headsetYawOffset) > 0.1) {  // Only if meaningful rotation
                    this.cameraRig.rotateLocal(0, -headsetYawOffset, 0);
                }

                this.needsVRCompensation = false;
            }
        }

        // Check for unassigned controllers and assign them once handedness is available
        // Only do this if we're missing at least one controller
        if (!this.leftController || !this.rightController) {
            const inputSources = (this.app.xr!.input as any).inputSources || [];
            for (let i = 0; i < inputSources.length; i++) {
                const source = inputSources[i];
                if (source && source.handedness) {
                    // This controller has handedness now!
                    if (source.handedness === 'left' && !this.leftController) {
                        this.leftController = source;
                        console.log('✅ Left controller assigned (handedness now available)');
                    } else if (source.handedness === 'right' && !this.rightController) {
                        this.rightController = source;
                        console.log('✅ Right controller assigned (handedness now available)');
                    }
                }
            }
        }

        // Check for exit VR input (left Y button or left menu button)
        if (this.leftController?.gamepad?.buttons) {
            const buttons = this.leftController.gamepad.buttons;
            // Y button is index 5, menu button is typically index 6 on Quest
            const leftYPressed = buttons[5]?.pressed || false;
            const leftMenuPressed = buttons[6]?.pressed || false;

            if (leftYPressed || leftMenuPressed) {
                console.log('Exit VR button pressed');
                this.app.xr!.end();
                return;
            }
        }

        // Since handedness is unreliable in the emulator, check BOTH controllers
        // for movement and rotation. Each controller's thumbstick is on axes[2-3]
        let moveForward = 0;
        let moveRight = 0;
        let rotateYaw = 0;

        // Check left controller (primarily for movement, but can also rotate)
        if (this.leftController?.gamepad) {
            const gamepad = this.leftController.gamepad;
            if (gamepad.axes.length >= 4) {
                const axisX = this.applyDeadzone(gamepad.axes[2]);
                const axisY = this.applyDeadzone(gamepad.axes[3]);

                // Use this for movement
                moveRight += axisX;
                moveForward += -axisY;
            }
        }

        // Check right controller (primarily for rotation, but can also move)
        if (this.rightController?.gamepad) {
            const gamepad = this.rightController.gamepad;
            if (gamepad.axes.length >= 4) {
                const axisX = this.applyDeadzone(gamepad.axes[2]);

                // Use this for rotation (yaw only)
                rotateYaw -= axisX;
            }
        }

        // Apply rotation (only yaw - pitch is handled by head tracking in VR)
        if (rotateYaw !== 0) {
            const deltaYaw = rotateYaw * this.rotationSpeed * dt;

            // Simple approach: rotate the rig but keep the camera at its current position
            // 1. Store camera's current world position
            const cameraWorldPos = this.camera.getPosition().clone();

            // 2. Rotate the rig
            this.cameraRig.rotateLocal(0, deltaYaw, 0);

            // 3. Move the rig so the camera ends up back at its original position
            const cameraNewPos = this.camera.getPosition();
            const correction = new pc.Vec3();
            correction.sub2(cameraWorldPos, cameraNewPos);
            this.cameraRig.setPosition(this.cameraRig.getPosition().add(correction));
        }

        // Apply movement in rig's local space (camera is child, so it follows)
        if (moveForward !== 0 || moveRight !== 0) {
            const forward = this.camera.forward.clone();
            const right = this.camera.right.clone();

            // Project onto horizontal plane
            forward.y = 0;
            right.y = 0;
            forward.normalize();
            right.normalize();

            const movement = new pc.Vec3();
            movement.add(forward.mulScalar(moveForward * this.moveSpeed * dt));
            movement.add(right.mulScalar(moveRight * this.moveSpeed * dt));

            const pos = this.cameraRig.getPosition();
            pos.add(movement);
            this.cameraRig.setPosition(pos);
        }

        // Check for vertical movement (Up/Down) using triggers
        // Left trigger: Down
        // Right trigger: Up
        let moveVertical = 0;

        // Left controller trigger (button index 0)
        if (this.leftController?.gamepad?.buttons[0]?.pressed) {
            // Use analog value if available, or just 1.0
            const val = this.leftController.gamepad.buttons[0].value || 1.0;
            moveVertical -= val;
        }

        // Right controller trigger (button index 0)
        if (this.rightController?.gamepad?.buttons[0]?.pressed) {
            const val = this.rightController.gamepad.buttons[0].value || 1.0;
            moveVertical += val;
        }

        if (moveVertical !== 0) {
            const pos = this.cameraRig.getPosition();
            pos.y += moveVertical * this.moveSpeed * dt;
            this.cameraRig.setPosition(pos);
        }
    }

    /**
     * Enable/disable VR controls
     */
    setEnabled(enabled: boolean) {
        this.enabled = enabled;
    }

    /**
     * Cleanup
     */
    destroy() {
        this.app.xr!.input.off('add', this.onInputSourceAdd);
        this.app.xr!.input.off('remove', this.onInputSourceRemove);
        this.leftController = null;
        this.rightController = null;

        // Restore camera to root if rig exists
        if (this.cameraRig && this.camera.parent === this.cameraRig) {
            const worldPos = this.camera.getPosition().clone();
            const worldRot = this.camera.getRotation().clone();
            this.camera.reparent(this.app.root);
            this.camera.setPosition(worldPos);
            this.camera.setRotation(worldRot);
            this.cameraRig.destroy();
        }
    }
}
