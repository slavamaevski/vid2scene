import {
	Controls,
	Camera,
	Vector2,
	Vector3
} from 'three';
import { FPSCameraController } from './FPSCameraController';

interface PointerLockControlsEventMap {
	change: Event & { type: 'change' };
	lock: Event & { type: 'lock' };
	unlock: Event & { type: 'unlock' };
}

const _changeEvent = new Event('change') as Event & { type: 'change' };
const _lockEvent = new Event('lock') as Event & { type: 'lock' };
const _unlockEvent = new Event('unlock') as Event & { type: 'unlock' };

class PointerLockControls extends Controls<PointerLockControlsEventMap> {

	public cameraController: FPSCameraController;
	public pointerLockMouseMoveScale: number = 0.002;
	public clickDragMouseMoveScale: number = 0.0015;
	public middleClickPanSpeed: number = 0.00075;
	public speed: number = 0.8;
	public verticalSpeed: number = 0.4;
	private _onMouseMove: (event: MouseEvent) => void;
	private _onKeyDown: (event: KeyboardEvent) => void;
	private _onKeyUp: (event: KeyboardEvent) => void;
	private _onPointerlockChange: () => void;
	private _onPointerlockError: () => void;
	private _keysPressed: Set<string>;
	private _movementDirection: Vector2;
	public worldUp: Vector3;

	// New properties for alternate controls
	public useClickDragControls: boolean = true;
	private isLeftMouseDown: boolean = false;
	private isRightMouseDown: boolean = false;
	private isMiddleMouseDown: boolean = false;

	constructor(camera: Camera, worldUp: Vector3, domElement: HTMLElement | null) {
		super(camera, domElement);

		this._keysPressed = new Set();
		this.worldUp = worldUp;
		this._movementDirection = new Vector2();
		this._onMouseMove = this.onMouseMove.bind(this);
		this._onPointerlockChange = onPointerlockChange.bind(this);
		this._onPointerlockError = onPointerlockError.bind(this);
		this._onKeyDown = this.onKeyDown.bind(this);
		this._onKeyUp = this.onKeyUp.bind(this);
		this.cameraController = new FPSCameraController(camera);
		this.cameraController.lock();
		if (this.domElement !== null) {
			this.connect();
		}
	}

	connect() {

		this.domElement?.ownerDocument.addEventListener('mousemove', this._onMouseMove);
		this.domElement?.ownerDocument.addEventListener('pointerlockchange', this._onPointerlockChange);
		this.domElement?.ownerDocument.addEventListener('pointerlockerror', this._onPointerlockError);
		this.domElement?.ownerDocument.addEventListener('keydown', this._onKeyDown);
		this.domElement?.ownerDocument.addEventListener('keyup', this._onKeyUp);

		// Add mouse button event listeners for alternate controls
		this.domElement?.addEventListener('mousedown', this.onMouseDown, false);
		this.domElement?.addEventListener('mouseup', this.onMouseUp, false);
		this.domElement?.addEventListener('contextmenu', this.onContextMenu, false);

		// Add wheel event listener
		this.domElement?.addEventListener('wheel', this.onWheel, { passive: false });
	}

	disconnect() {
		this.domElement?.ownerDocument.removeEventListener('mousemove', this._onMouseMove);
		this.domElement?.ownerDocument.removeEventListener('pointerlockchange', this._onPointerlockChange);
		this.domElement?.ownerDocument.removeEventListener('pointerlockerror', this._onPointerlockError);
		this.domElement?.ownerDocument.removeEventListener('keydown', this._onKeyDown);
		this.domElement?.ownerDocument.removeEventListener('keyup', this._onKeyUp);

		// Remove mouse button event listeners
		this.domElement?.removeEventListener('mousedown', this.onMouseDown);
		this.domElement?.removeEventListener('mouseup', this.onMouseUp);
		this.domElement?.removeEventListener('contextmenu', this.onContextMenu);

		// Remove wheel event listener
		this.domElement?.removeEventListener('wheel', this.onWheel);
	}

	dispose() {
		this.disconnect();
	}

	onMouseMove(event: MouseEvent): void {
		if (this.useClickDragControls) {
			if (this.isMiddleMouseDown) {
				const panOffsetX = -event.movementX * this.middleClickPanSpeed;
				const panOffsetY = event.movementY * this.middleClickPanSpeed;
				this.cameraController.moveRight(panOffsetX);
				this.cameraController.moveUp(panOffsetY);
				this.dispatchEvent(_changeEvent);
			} else if (this.isLeftMouseDown) {
				this.cameraController.applyRotation(
					-event.movementY * this.clickDragMouseMoveScale,
					event.movementX * this.clickDragMouseMoveScale,
					this.worldUp
				);
				this.dispatchEvent(_changeEvent);
			}
		} else {
			this.cameraController.applyRotation(
				event.movementY * this.pointerLockMouseMoveScale,
				-event.movementX * this.pointerLockMouseMoveScale,
				this.worldUp
			);
			this.dispatchEvent(_changeEvent);
		}
	}

	onKeyDown(event: KeyboardEvent): void {
		if (event.code === 'Space') {
			// If useClickDragControls is true, we are currently in click drag mode
			// and we want to switch to pointer lock mode
			this.setPointerLock(this.useClickDragControls);
			return;
		}
		this._keysPressed.add(event.key);
	}

	onKeyUp(event: KeyboardEvent): void {
		this._keysPressed.delete(event.key);
	}

	lock() {
		this.domElement?.requestPointerLock();
		//this.cameraController.lock();
		this.dispatchEvent(_lockEvent);
	}

	unlock() {
		this.domElement?.ownerDocument.exitPointerLock();
		//this.cameraController.unlock();
		this.dispatchEvent(_unlockEvent);
	}

	roll(angle: number) {
		this.cameraController.roll(angle);
	}

	update(deltaTime: number) {
		this._movementDirection.set(0, 0);
		// Handle keyboard input
		if (this._keysPressed.has('w') || this._keysPressed.has('W') || this._keysPressed.has('ArrowUp')) {
			this._movementDirection.y += 1;
		}
		if (this._keysPressed.has('s') || this._keysPressed.has('S') || this._keysPressed.has('ArrowDown')) {
			this._movementDirection.y -= 1;
		}
		if (this._keysPressed.has('a') || this._keysPressed.has('A') || this._keysPressed.has('ArrowLeft')) {
			this._movementDirection.x -= 1;
		}
		if (this._keysPressed.has('d') || this._keysPressed.has('D') || this._keysPressed.has('ArrowRight')) {
			this._movementDirection.x += 1;
		}

		// If alternate controls mode is active and right mouse is pressed, move forward
		if (this.useClickDragControls && this.isRightMouseDown) {
			this.cameraController.moveForward(this.speed * deltaTime);
		}

		// Apply movement based on WASD/Arrow keys
		if (this._movementDirection.lengthSq() > 0.0) {
			this._movementDirection.normalize();
			this.cameraController.moveForward(this._movementDirection.y * this.speed * deltaTime);
			this.cameraController.moveRight(this._movementDirection.x * this.speed * deltaTime);
		}

		// Add vertical movement based on key states
		if (this._keysPressed.has('Shift')) {
			this.cameraController.moveUp(this.verticalSpeed * deltaTime);
			this.dispatchEvent(_changeEvent);
		}
		if (this._keysPressed.has('Control')) {
			this.cameraController.moveUp(-this.verticalSpeed * deltaTime);
			this.dispatchEvent(_changeEvent);
		}
	}

	// New method to toggle control modes
	private setPointerLock(enableLock: boolean) {
		if (!enableLock) {
			console.log('Switched to Click Drag Controls.');
			this.unlock(); // Release pointer lock when switching to Alternate Controls
		} else {
			console.log('Switched to PointerLock Controls.');
			this.lock(); // Request pointer lock when switching to PointerLock Controls
		}
	}

	// New event handlers for mouse buttons
	private onMouseDown = (event: MouseEvent) => {
		if (this.useClickDragControls) {
			if (event.button === 0) { // Left button
				this.isLeftMouseDown = true;
			} else if (event.button === 1) { // Middle button
				this.isMiddleMouseDown = true;
				event.preventDefault();
			} else if (event.button === 2) { // Right button
				this.isRightMouseDown = true;
			}
		}
	}

	private onMouseUp = (event: MouseEvent) => {
		if (this.useClickDragControls) {
			if (event.button === 0) { // Left button
				this.isLeftMouseDown = false;
			} else if (event.button === 1) { // Middle button
				this.isMiddleMouseDown = false;
			} else if (event.button === 2) { // Right button
				this.isRightMouseDown = false;
			}
		}
	}

	// Prevent context menu on right-click when using alternate controls
	private onContextMenu = (event: MouseEvent) => {
		if (this.useClickDragControls) {
			event.preventDefault();
		}
	}

	// Add wheel handler method
	private onWheel = (event: WheelEvent) => {
		event.preventDefault();
		// Negative deltaY means scrolling up (move forward)
		// Positive deltaY means scrolling down (move backward)
		this.cameraController.moveForward(-event.deltaY * 0.001 * this.speed);
		this.dispatchEvent(_changeEvent);
	}
}

function onPointerlockChange(this: PointerLockControls): void {

	if (this.domElement?.ownerDocument.pointerLockElement === this.domElement) {

		this.dispatchEvent(_lockEvent);

		this.useClickDragControls = false;

	} else {

		this.dispatchEvent(_unlockEvent);

		this.useClickDragControls = true;

	}

}

function onPointerlockError(): void {

	console.error('THREE.PointerLockControls: Unable to use Pointer Lock API');

}

export { PointerLockControls };