import {FPSCameraController} from './FPSCameraController';
import { Controls, Camera, Vector2, Vector3 } from 'three';
import nipplejs from 'nipplejs';
import { getJoystickDirection } from '../math';

interface JoystickTouchControlsEventMap {
	change: Event & { type: 'change' };
}


class JoystickTouchControls extends Controls<JoystickTouchControlsEventMap> {
    
	public cameraController: FPSCameraController;
	public movementSpeed: number = 0.8; // Units per second
	public rotationJoystickSensitivity: number = 0.9; // Radians per second
    public rotationTouchSensitivity: number = 0.0025; // Radians per pixel
    public joystickDeadzone: number = 0.025; // Squared length of joystick deadzone
    public touchPanSpeed: number = 0.003;
    public pinchZoomSpeed: number = 0.005; // Adjust zoom speed as needed
    public worldUp: Vector3;
    
	private _movementDirection: Vector2;
    private _rotationDirection: Vector2;
    private _movementJoystickManager: nipplejs.JoystickManager | null = null;
    private _rotationJoystickManager: nipplejs.JoystickManager | null = null;
    
    // Touch handling properties
    private _isTouchDragging: boolean = false;
    private _lastTouchPosition: Vector2 = new Vector2();

    // Properties for two-finger pan
    private _isPanGesture: boolean = false;
    private _initialPanPositions: [Vector2, Vector2] = [new Vector2(), new Vector2()];

    // Properties for two-finger pinch zoom
    private _isPinching: boolean = false;
    private _initialPinchDistance: number = 0;

	constructor(camera: Camera, worldUp: Vector3, domElement: HTMLElement | null, movementJoystickManager: nipplejs.JoystickManager, rotationJoystickManager: nipplejs.JoystickManager) {
		super(camera, domElement);
        this.worldUp = worldUp;

		this._movementDirection = new Vector2();
        this._rotationDirection = new Vector2();
        this._movementJoystickManager = movementJoystickManager;
        this._rotationJoystickManager = rotationJoystickManager;
		this.cameraController = new FPSCameraController(camera);
		if (this.domElement !== null) {
			this.connect();
		}
        this.cameraController.lock();
	}

    connect() {
        // Initialize touch event listeners
        if (this.domElement) {
            this.domElement.addEventListener('touchstart', this.onTouchStart, false);
            this.domElement.addEventListener('touchmove', this.onTouchMove, false);
            this.domElement.addEventListener('touchend', this.onTouchEnd, false);
        }
    }

    disconnect() {
        // Remove touch event listeners
        if (this.domElement) {
            this.domElement.removeEventListener('touchstart', this.onTouchStart);
            this.domElement.removeEventListener('touchmove', this.onTouchMove);
            this.domElement.removeEventListener('touchend', this.onTouchEnd);
        }
    }

    dispose() {
        this.disconnect();
    }

    roll(angle: number) {
        this.cameraController.roll(angle);
    }

	update(deltaTime: number) {
        if (this._movementJoystickManager && this._movementJoystickManager.ids.length > 0) {
            const id = this._movementJoystickManager.ids[0];
            const movementJoystick = this._movementJoystickManager.get(id);
            if (movementJoystick) {
                const movementDirection = getJoystickDirection(movementJoystick);
                this._movementDirection.set(movementDirection.x, movementDirection.y);
                const directionLengthSquared = this._movementDirection.lengthSq();
                if (directionLengthSquared > this.joystickDeadzone) {
                    if (directionLengthSquared > 1.0) {
                        this._movementDirection.normalize();
                    }
                    this.cameraController.moveForward(this._movementDirection.y * this.movementSpeed * deltaTime);
                    this.cameraController.moveRight(this._movementDirection.x * this.movementSpeed * deltaTime);
                }
            }
        }

        if (this._rotationJoystickManager && this._rotationJoystickManager.ids.length > 0) {
            const id = this._rotationJoystickManager.ids[0];
            const rotationJoystick = this._rotationJoystickManager.get(id);
            if (rotationJoystick) {
                const rotationDirection = getJoystickDirection(rotationJoystick);
                this._rotationDirection.set(rotationDirection.x, rotationDirection.y);
                const directionLengthSquared = this._rotationDirection.lengthSq();
                if (directionLengthSquared > this.joystickDeadzone) {
                    this.cameraController.applyRotation(
                        -this._rotationDirection.y * this.rotationJoystickSensitivity * deltaTime, 
                        -this._rotationDirection.x * this.rotationJoystickSensitivity * deltaTime, 
                        this.worldUp
                    );
                }
            }
        }
	}

    private onTouchStart = (event: TouchEvent) => {
        if (event.touches.length === 1) { // Single touch for rotation
            this._isTouchDragging = true;
            this._lastTouchPosition.set(event.touches[0].clientX, event.touches[0].clientY);
        } else if (event.touches.length === 2) { // Two-finger touch for panning and pinch zoom
            const touch1 = event.touches[0];
            const touch2 = event.touches[1];
            this._isPanGesture = true;

            // Initialize pan positions
            this._initialPanPositions = [
                new Vector2(touch1.clientX, touch1.clientY),
                new Vector2(touch2.clientX, touch2.clientY)
            ];

            // Initialize pinch zoom
            const dx = touch2.clientX - touch1.clientX;
            const dy = touch2.clientY - touch1.clientY;
            this._initialPinchDistance = Math.sqrt(dx * dx + dy * dy);
            this._isPinching = true;
        }
    }

    private onTouchMove = (event: TouchEvent) => {
        if (this._isPanGesture && event.touches.length === 2) {
            const touch1 = event.touches[0];
            const touch2 = event.touches[1];
            const currentPanPositions: [Vector2, Vector2] = [
                new Vector2(touch1.clientX, touch1.clientY),
                new Vector2(touch2.clientX, touch2.clientY)
            ];

            // Calculate the average movement for panning
            const delta1 = currentPanPositions[0].clone().sub(this._initialPanPositions[0]);
            const delta2 = currentPanPositions[1].clone().sub(this._initialPanPositions[1]);
            const averageDelta = delta1.add(delta2).multiplyScalar(0.5);

            // Update initial pan positions for the next move event
            this._initialPanPositions = currentPanPositions;

            // Convert screen delta to world delta
            const panOffsetX = -averageDelta.x * this.touchPanSpeed;
            const panOffsetY = averageDelta.y * this.touchPanSpeed;

            // Apply panning using camera controller's moveRight and moveUp
            this.cameraController.moveRight(panOffsetX);
            this.cameraController.moveUp(panOffsetY);

            // Handle pinch zoom
            if (this._isPinching) {
                const dx = currentPanPositions[1].x - currentPanPositions[0].x;
                const dy = currentPanPositions[1].y - currentPanPositions[0].y;
                const currentDistance = Math.sqrt(dx * dx + dy * dy);
                const pinchDelta = currentDistance - this._initialPinchDistance;
                this._initialPinchDistance = currentDistance;

                // Apply zoom based on pinch delta
                const zoomMovement = pinchDelta * this.pinchZoomSpeed;
                this.cameraController.moveForward(zoomMovement);
            }
        } else if (this._isTouchDragging && event.touches.length === 1) { // Single touch for rotation
            const touch = event.touches[0];
            const currentPosition = new Vector2(touch.clientX, touch.clientY);
            const delta = currentPosition.clone().sub(this._lastTouchPosition);
            this._lastTouchPosition.copy(currentPosition);
            
            // Apply rotation based on touch movement
            this.cameraController.applyRotation(
                -delta.y * this.rotationTouchSensitivity,
                delta.x * this.rotationTouchSensitivity,
                this.worldUp
            );
        }
    }

    private onTouchEnd = (event: TouchEvent) => {
        if (this._isPanGesture && event.touches.length < 2) {
            this._isPanGesture = false;
            this._isPinching = false;
            
            // If one finger remains, initiate touch dragging for rotation
            if (event.touches.length === 1) {
                this._isTouchDragging = true;
                const remainingTouch = event.touches[0];
                this._lastTouchPosition.set(remainingTouch.clientX, remainingTouch.clientY);
            }
        }
        if (this._isTouchDragging && event.touches.length === 0) {
            this._isTouchDragging = false;
        }
    }

}

export { JoystickTouchControls };