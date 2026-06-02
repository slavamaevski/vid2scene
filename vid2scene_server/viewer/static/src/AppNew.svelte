<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { fade, slide } from "svelte/transition";
  import { Tooltip } from "@sveltestrap/sveltestrap";
  import {
    Facebook,
    X,
    LinkedIn,
    Email,
    WhatsApp,
    Telegram,
    Reddit,
  } from "svelte-share-buttons-component/src";
  import { copy } from "svelte-copy";

  import samusynthLogo from "./assets/samusynth_logo.webp";
  import closeIcon from "./assets/close-circle-svgrepo-com.svg";
  import gearIcon from "./assets/gear-configuration-interface-svgrepo-com.svg";
  import orbitalViewIcon from "./assets/orbital-view-icon.svg";
  import droneViewIcon from "./assets/drone-view-icon.svg";
  import vrIcon from "./assets/vr-icon.svg";
  import shareIcon from "./assets/share.svg";
  import * as pc from "playcanvas";
  import nipplejs from "nipplejs";
  import { getDataAttribute } from "./getDataAttribute";
  import Shepherd from "shepherd.js";
  import "shepherd.js/dist/css/shepherd.css";
  import type { CameraData, ParsedCameraData } from "./types/CameraData";
  import { createTour } from "./tours/ViewerTour";
  import { PlayCanvasJoystickControls } from "./controls/PlayCanvasJoystickControls";
  import { PlayCanvasFlyControls } from "./controls/PlayCanvasFlyControls";
  import { PlayCanvasOrbitControls } from "./controls/PlayCanvasOrbitControls";
  import { GroundPlaneIndicator } from "./controls/GroundPlaneIndicator";
  import { SceneAlignerControls } from "./controls/SceneAlignerControls";
  import { XRManager } from "./controls/XRManager";
  import { loadSpzAsPlayCanvasAsset } from "./spzLoader";
  import { loadLodAsPlayCanvasAsset } from "./lodLoader";

  // Global type declarations
  interface Window {
    umami?: {
      track: (eventName: string, eventProps?: Record<string, any>) => void;
    };
  }

  let app: pc.Application;
  let camera: pc.Entity;
  let gsEntity: pc.Entity;
  let sceneRotation: pc.Quat = new pc.Quat(); // Track the scene's rotation for camera roll
  let sceneAlignerControls: SceneAlignerControls | null = null;
  let spjId: string | null = null;
  let tour: Shepherd.Tour | undefined = undefined;

  let sceneLoaded = false;
  let logoLoaded = false;
  let backgroundLoaded = false;
  let showMenu = false;
  let debugLodColorize = false;
  let useLodFile = false;
  let showShareMenu = false;
  let isOwner = false;
  let isShareable = false;
  let useFPSControls = true;
  let modeBeforeSceneAlignment: boolean | null = null; // Track mode before entering scene alignment
  let groundPlaneVisibleBeforeAlignment: boolean = false; // Track ground plane visibility before scene alignment
  let isMobile = false;
  let title = getDataAttribute("title");
  let loadingStatus = "Loading...";
  let showSlowLoadingMessage = false;
  let slowLoadingTimeout: number;
  document.body.setAttribute("data-show-joystick", "true");

  let movementJoystickManager: nipplejs.JoystickManager | null = null;
  let rotationJoystickManager: nipplejs.JoystickManager | null = null;
  let orbitControls: PlayCanvasOrbitControls | null = null;
  let flyControls: PlayCanvasFlyControls | null = null;
  let joystickControls: PlayCanvasJoystickControls | null = null;
  let groundPlaneIndicator: GroundPlaneIndicator | null = null;

  // XR/VR support
  let xrSupported: boolean = false;
  let isInXR: boolean = false;
  let xrManager: XRManager | null = null;

  // Reference to the joystick zone DOM element
  let movementJoystickZone: HTMLElement;
  let rotationJoystickZone: HTMLElement;

  // Compute the preview image URL
  $: previewImageUrl = spjId ? `/preview/${spjId}/` : "";

  let showCopiedMessage = false;
  let copyMessageTimeout: number;

  // Function to detect if the device is mobile
  function detectMobile() {
    return /Mobi|Android/i.test(navigator.userAgent);
  }
  function isIOS() {
    return (
      [
        "iPad Simulator",
        "iPhone Simulator",
        "iPod Simulator",
        "iPad",
        "iPhone",
        "iPod",
      ].includes(navigator.platform) ||
      // iPad on iOS 13 detection
      (navigator.userAgent.includes("Mac") && "ontouchend" in document)
    );
  }

  function getDownloadUrl(spjId: string, useSpzFile: boolean) {
    return useSpzFile ? `/download/${spjId}/` : `/downloadPly/${spjId}/`;
  }

  function getSogUrlsEndpoint(spjId: string) {
    return `/sog/${spjId}/`;
  }

  function getLodUrlsEndpoint(spjId: string) {
    return `/lod/${spjId}/`;
  }

  // Function to save camera position
  async function saveCameraInfo(overriddenCameraMode?: boolean) {
    if (!camera || !gsEntity) return;

    if (
      !confirm(
        "Are you sure you want to save the current camera position as the default view?",
      )
    ) {
      return;
    }

    const cameraPosition = camera.getPosition();

    // Use overridden mode if provided, otherwise use current mode
    const isFPSMode =
      overriddenCameraMode !== undefined
        ? overriddenCameraMode
        : useFPSControls;

    let cameraLookAt: pc.Vec3;
    if (isFPSMode && flyControls) {
      // For fly controls, calculate look-at based on camera forward direction
      const forward = camera.forward.clone();
      cameraLookAt = cameraPosition.clone().add(forward);
    } else if (orbitControls) {
      cameraLookAt = orbitControls.pivotPoint;
    } else {
      // Default look-at
      cameraLookAt = new pc.Vec3(1, 0, 0);
    }

    // Transform from world space back to original data space
    // This is the inverse of what happens on load
    // Account for both rotation AND position of the gsEntity
    const gsRotation = gsEntity.getRotation();
    const gsPosition = gsEntity.getPosition();
    const inverseRotation = gsRotation.clone().invert();

    const originalPosition = new pc.Vec3();
    const originalLookAt = new pc.Vec3();
    const originalUp = new pc.Vec3();

    // First subtract the scene's position to get scene-relative coordinates
    const relativePosition = new pc.Vec3().sub2(cameraPosition, gsPosition);
    const relativeLookAt = new pc.Vec3().sub2(cameraLookAt, gsPosition);

    // Then apply inverse rotation to transform to original data space
    inverseRotation.transformVector(relativePosition, originalPosition);
    inverseRotation.transformVector(relativeLookAt, originalLookAt);

    // For the up vector: transform world Y-up back to original space
    // This represents "which direction in original space should be considered up"
    const worldYUp = new pc.Vec3(0, 1, 0);
    inverseRotation.transformVector(worldYUp, originalUp);

    const cameraData: CameraData = {
      position: {
        x: originalPosition.x,
        y: originalPosition.y,
        z: originalPosition.z,
      },
      lookAt: { x: originalLookAt.x, y: originalLookAt.y, z: originalLookAt.z },
      up: { x: originalUp.x, y: originalUp.y, z: originalUp.z },
      cameraType: isFPSMode ? "drone" : "orbital",
    };

    try {
      const response = await fetch(
        `/web_api/scene-processing-jobs/${spjId}/camera-data/`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCookie("csrftoken"),
          },
          body: JSON.stringify({
            camera_data: cameraData,
          }),
        },
      );

      if (response.ok) {
        alert("Camera position saved successfully!");
      } else {
        throw new Error("Failed to save camera position");
      }
    } catch (error) {
      console.error("Error saving camera position:", error);
      alert("Failed to save camera position");
    }
  }

  function showGroundPlane() {
    if (groundPlaneIndicator) {
      groundPlaneIndicator.toggle();
      // Update position if we're in orbit mode and it's now visible
      if (groundPlaneIndicator.isVisible() && orbitControls) {
        groundPlaneIndicator.setPosition(orbitControls.pivotPoint);
      }
    }
  }

  async function toggleSceneRotationMode(shouldSaveCamera: boolean = true) {
    // If entering scene alignment mode
    if (!sceneAlignerControls || !sceneAlignerControls.isActive) {
      // Save the current mode and ground plane state
      modeBeforeSceneAlignment = useFPSControls;
      groundPlaneVisibleBeforeAlignment = groundPlaneIndicator
        ? groundPlaneIndicator.isVisible()
        : false;

      // If we're in drone mode, switch to orbital mode for scene alignment
      if (useFPSControls) {
        await switchToOrbitalModeAndWait();
      }

      // Create or recreate SceneAlignerControls AFTER switching to orbital mode
      // This ensures it has the correct orbital controls reference
      sceneAlignerControls = new SceneAlignerControls(
        app,
        camera,
        gsEntity,
        sceneRotation,
        groundPlaneIndicator,
        orbitControls,
        flyControls,
      );

      sceneAlignerControls.toggle();

      // Explicitly disable joystick controls
      if (joystickControls) joystickControls.enabled = false;
    } else {
      // Exiting scene alignment mode
      sceneAlignerControls.toggle();

      // Re-enable joystick controls
      if (joystickControls) joystickControls.enabled = true;

      // Restore original mode if needed
      if (
        modeBeforeSceneAlignment !== null &&
        modeBeforeSceneAlignment !== useFPSControls
      ) {
        // Restore the original mode by toggling
        const fakeEvent = new Event("click");
        toggleControls(fakeEvent);
      }

      // Restore ground plane visibility if it wasn't visible before
      if (
        groundPlaneIndicator &&
        !groundPlaneVisibleBeforeAlignment &&
        groundPlaneIndicator.isVisible()
      ) {
        groundPlaneIndicator.toggle();
      }

      // Save camera data only if requested (Apply, not Undo)
      if (shouldSaveCamera) {
        if (modeBeforeSceneAlignment !== null) {
          saveCameraInfo(modeBeforeSceneAlignment);
        } else {
          saveCameraInfo();
        }
      }

      // Clear the saved states
      modeBeforeSceneAlignment = null;
      groundPlaneVisibleBeforeAlignment = false;
    }

    // Close settings menu when entering scene rotation mode
    if (sceneAlignerControls.isActive && showMenu) {
      showMenu = false;
    }

    // Force Svelte to detect the change
    sceneAlignerControls = sceneAlignerControls;

    // Ensure orbital controls stay enabled when scene rotation is active
    if (sceneAlignerControls.isActive && orbitControls) {
      orbitControls.enabled = true;
    }
  }

  // Helper function to switch to orbital mode and wait for raycast to complete
  async function switchToOrbitalModeAndWait() {
    useFPSControls = false;
    document.body.removeAttribute("data-show-joystick");

    if (flyControls) {
      flyControls.enabled = false;
    }

    if (orbitControls) {
      orbitControls.enabled = true;
      // Raycast forward to find a new pivot point and wait for it to complete
      const success = await orbitControls.raycastAndSetPivot(true);

      if (!success) {
        // Raycast failed completely, use 1 meter forward as fallback
        const cameraPos = camera.getPosition();
        const forward = camera.forward.clone().mulScalar(1.0);
        orbitControls.pivotPoint.copy(cameraPos.clone().add(forward));
        orbitControls.recalculateFromCameraAndPivot();
        console.log("Raycast failed, using 1 meter forward fallback");
      }
    } else {
      orbitControls = new PlayCanvasOrbitControls(
        app.mouse,
        camera,
        app.touch,
        app,
      );
      // Raycast to find initial pivot point and wait for it to complete
      const success = await orbitControls.raycastAndSetPivot(true);

      if (!success) {
        // Raycast failed completely, use 1 meter forward as fallback
        const cameraPos = camera.getPosition();
        const forward = camera.forward.clone().mulScalar(1.0);
        orbitControls.pivotPoint.copy(cameraPos.clone().add(forward));
        orbitControls.recalculateFromCameraAndPivot();
        console.log("Raycast failed, using 1 meter forward fallback");
      }
    }
  }

  // Helper function to get CSRF token
  function getCookie(name: string) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop()?.split(";").shift();
    return null;
  }

  function parseCameraData(
    jsonString: string | null | undefined,
  ): ParsedCameraData {
    const default_camera_info: ParsedCameraData = {
      initialCameraPosition: [0.0, 0.0, 0.0],
      initialCameraLookAt: [1.0, 0.0, 0.0],
      cameraUp: [0.0, 0.0, -1.0],
      useDroneControls: true, // Default to drone controls
    };

    if (!jsonString) {
      console.info("No camera data found. Using default.");
      return default_camera_info;
    }

    try {
      let json = JSON.parse(jsonString);
      if (typeof json === "string") {
        json = JSON.parse(json);
      }
      const serverCameraData = json as CameraData;

      // Default to drone controls if cameraType is not specified
      if (serverCameraData.cameraType === undefined) {
        serverCameraData.cameraType = "drone";
      }

      return {
        initialCameraPosition: [
          serverCameraData.position.x,
          serverCameraData.position.y,
          serverCameraData.position.z,
        ],
        initialCameraLookAt: [
          serverCameraData.lookAt.x,
          serverCameraData.lookAt.y,
          serverCameraData.lookAt.z,
        ],
        cameraUp: [
          serverCameraData.up.x,
          serverCameraData.up.y,
          serverCameraData.up.z,
        ],
        useDroneControls: serverCameraData.cameraType === "drone",
      };
    } catch (error) {
      console.error("Failed to parse camera data. Using default.");
      return default_camera_info;
    }
  }

  // Function to initialize the PlayCanvas viewer
  const initializeViewer = async () => {
    spjId = getDataAttribute("spj-id");
    const urlParams = new URLSearchParams(window.location.search);
    const forceLoadPly = urlParams.get("forceLoadPly") === "true";
    const forceLoadSpz = urlParams.get("forceLoadSpz") === "true";
    const forceLoadLod = urlParams.get("forceLoadLod") === "true";
    const hasSpzAvailable =
      getDataAttribute("has-spz-available")?.toLowerCase() === "true";
    const hasSogAvailable =
      getDataAttribute("has-sog-available")?.toLowerCase() === "true";
    const hasLodAvailable =
      getDataAttribute("has-lod-available")?.toLowerCase() === "true";

    // Loading priority: LOD > SOG > SPZ > PLY
    // LOD is the preferred format (streaming octree, only loads visible chunks)
    let fileFormat: "lod" | "sog" | "spz" | "ply" = "ply";
    if (hasSpzAvailable) fileFormat = "spz";
    if (hasSogAvailable) fileFormat = "sog";
    if (hasLodAvailable) fileFormat = "lod";

    // URL params can override
    if (forceLoadSpz) fileFormat = "spz";
    if (forceLoadPly) fileFormat = "ply";
    if (forceLoadLod) fileFormat = "lod";

    const useSpzFile = fileFormat === "spz";
    const useSogFile = fileFormat === "sog";
    useLodFile = fileFormat === "lod";

    const downloadUrl =
      useSpzFile || fileFormat === "ply"
        ? getDownloadUrl(spjId, useSpzFile)
        : "";

    let sceneUrl = downloadUrl;
    const serverCameraData =
      document.getElementById("server_camera_data")?.textContent;

    isOwner = getDataAttribute("is-owner")?.toLowerCase() === "true";
    isShareable = getDataAttribute("is-shareable")?.toLowerCase() === "true";

    const cameraInfo = parseCameraData(serverCameraData);
    useFPSControls = cameraInfo.useDroneControls;

    // PlayCanvas handles its own render loop, we just need to set up the app

    const setLoadingStatus = (action: string, percent: number) => {
      loadingStatus = `${action}... ${Math.round(percent)}%`;
    };

    const startRendering = () => {
      if (slowLoadingTimeout) clearTimeout(slowLoadingTimeout);
      document.body.style.backgroundColor = "#111111";

      // Add small delay before hiding loading screen to prevent black flash
      setTimeout(() => {
        sceneLoaded = true;
        initTour();
      }, 300);
    };

    // Create PlayCanvas canvas
    const canvas = document.createElement("canvas");
    canvas.id = "playcanvas-canvas";
    canvas.style.position = "fixed";
    canvas.style.top = "0";
    canvas.style.left = "0";
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.zIndex = "0";
    canvas.style.touchAction = "none"; // Prevent browser touch gestures (pinch zoom, etc.)

    // Prevent right-click context menu on the canvas
    canvas.addEventListener("contextmenu", (event) => {
      event.preventDefault();
    });

    document.body.appendChild(canvas);

    // Create PlayCanvas Application (simpler than AppBase for our use case)
    app = new pc.Application(canvas, {
      mouse: new pc.Mouse(canvas),
      touch: new pc.TouchDevice(canvas),
      keyboard: new pc.Keyboard(window),
    });

    // Configure canvas rendering
    app.setCanvasFillMode(pc.FILLMODE_FILL_WINDOW);
    app.setCanvasResolution(pc.RESOLUTION_AUTO);

    // Set up camera
    camera = new pc.Entity("camera");
    camera.addComponent("camera", {
      clearColor: new pc.Color(0.067, 0.067, 0.067), // Dark background
      nearClip: 0.01,
      farClip: 1000,
    });

    // Set up Overlay layer for UI elements that render on top of everything
    let overlayLayer = app.scene.layers.getLayerByName("Overlay");
    if (!overlayLayer) {
      overlayLayer = new pc.Layer({
        name: "Overlay",
        opaqueSortMode: pc.SORTMODE_NONE,
        transparentSortMode: pc.SORTMODE_BACK2FRONT,
      });

      // Insert at the end of the layer composition
      app.scene.layers.insert(overlayLayer, app.scene.layers.layerList.length);

      // Add overlay layer to camera's render layers
      camera.camera.layers.push(overlayLayer.id);

      console.log("Overlay layer created with ID:", overlayLayer.id);
      console.log("Layer list length:", app.scene.layers.layerList.length);
      console.log("Camera layers:", camera.camera.layers);
    }

    // Initialize ground plane indicator
    groundPlaneIndicator = new GroundPlaneIndicator(app);

    // Calculate rotation to transform from data's coordinate system to PlayCanvas Y-up
    const dataUp = new pc.Vec3(
      cameraInfo.cameraUp[0],
      cameraInfo.cameraUp[1],
      cameraInfo.cameraUp[2],
    ).normalize();
    const playcanvasUp = new pc.Vec3(0, 1, 0);

    // Calculate rotation quaternion that rotates dataUp to playcanvasUp
    const rotationQuat = new pc.Quat();
    rotationQuat.setFromDirections(dataUp, playcanvasUp);

    // Store the initial scene rotation
    sceneRotation.copy(rotationQuat);

    // Transform camera position and lookAt using this rotation
    const transformPoint = (point: number[]) => {
      const vec = new pc.Vec3(point[0], point[1], point[2]);
      rotationQuat.transformVector(vec, vec);
      return vec;
    };

    const transformedPosition = transformPoint(
      cameraInfo.initialCameraPosition,
    );
    const transformedLookAt = transformPoint(cameraInfo.initialCameraLookAt);

    // Set initial camera position and orientation
    camera.setPosition(
      transformedPosition.x,
      transformedPosition.y,
      transformedPosition.z,
    );

    // IMPORTANT: Add camera to scene hierarchy BEFORE lookAt, so the rotation is properly calculated
    app.root.addChild(camera);

    // Now set the camera orientation
    camera.lookAt(
      transformedLookAt.x,
      transformedLookAt.y,
      transformedLookAt.z,
    );

    // Create Gaussian Splatting entity and apply the same rotation
    gsEntity = new pc.Entity("gaussian-splatting");
    gsEntity.setLocalRotation(sceneRotation);
    app.root.addChild(gsEntity);

    // Set up controls based on mode (now using PlayCanvas Y-up after transformation)
    // IMPORTANT: Initialize controls AFTER camera orientation is set
    if (useFPSControls) {
      // Fly controls for drone mode
      flyControls = new PlayCanvasFlyControls(app.mouse, camera, canvas);
      if (useLodFile) {
        flyControls.moveSpeed = 5.0;
      }
      // Use PlayCanvas standard Y-up since we've transformed everything
      flyControls.worldUp = new pc.Vec3(0, 1, 0);
      document.body.setAttribute("data-show-joystick", "true");
    } else {
      // Orbit controls for orbital mode
      orbitControls = new PlayCanvasOrbitControls(
        app.mouse,
        camera,
        app.touch,
        app,
      );
      orbitControls.pivotPoint.set(
        transformedLookAt.x,
        transformedLookAt.y,
        transformedLookAt.z,
      );
      // Recalculate yaw/pitch/distance from the loaded camera position
      orbitControls.recalculateFromCameraAndPivot();
      document.body.removeAttribute("data-show-joystick");
    }

    // Set up unified update loop for all control schemes
    app.on("update", (dt: number) => {
      if (flyControls && flyControls.enabled) {
        flyControls.update(dt);
      }

      if (orbitControls && orbitControls.enabled) {
        orbitControls.update(dt);
        // Update ground plane position to follow pivot point
        if (groundPlaneIndicator && groundPlaneIndicator.isVisible()) {
          groundPlaneIndicator.setPosition(orbitControls.pivotPoint);
        }
      }

      // Update joystick controls (framerate independent)
      if (joystickControls) {
        joystickControls.update(dt);
      }

      // Update XR manager (VR controls)
      if (xrManager) {
        xrManager.update(dt);
      }

      if (sceneAlignerControls && sceneAlignerControls.isActive) {
        sceneAlignerControls.update();
        // Update ground plane position to follow pivot point during scene rotation
        if (
          groundPlaneIndicator &&
          groundPlaneIndicator.isVisible() &&
          orbitControls
        ) {
          groundPlaneIndicator.setPosition(orbitControls.pivotPoint);
        }
      }
    });

    // Start the application (this begins the render loop)
    app.start();

    // Initialize XR manager (after app is started)
    const initialCameraPosition = camera.getPosition().clone();
    const initialCameraRotation = camera.getRotation().clone();
    xrManager = new XRManager(
      app,
      camera,
      initialCameraPosition,
      initialCameraRotation,
    );

    // Set up XR event handlers
    xrManager.onStart(() => {
      isInXR = true;
      // Disable other controls when in VR
      if (orbitControls) orbitControls.enabled = false;
      if (flyControls) flyControls.enabled = false;
      if (joystickControls) joystickControls.enabled = false;
    });

    xrManager.onEnd(() => {
      isInXR = false;
      // Re-enable controls based on current mode
      if (useFPSControls) {
        if (flyControls) flyControls.enabled = true;
        if (joystickControls) joystickControls.enabled = true;
      } else {
        if (orbitControls) orbitControls.enabled = true;
      }
    });

    // Load Gaussian Splatting asset
    const loadGSAsset = async () => {
      try {
        if (useLodFile) {
          // LOD: stream octree chunks directly from Azure Blob Storage via Service Worker
          try {
            const endpoint = getLodUrlsEndpoint(spjId);

            const response = await fetch(endpoint);
            if (!response.ok) {
              throw new Error(
                `Failed to fetch LOD URL map: ${response.status}`,
              );
            }
            const sasUrls = await response.json();

            await loadLodAsPlayCanvasAsset(
              app,
              gsEntity,
              sasUrls,
              spjId,
              (status, percent) => setLoadingStatus(status, percent),
            );
            startRendering();
          } catch (lodError) {
            console.error("Failed to load LOD file:", lodError);
            console.error("Falling back to SOG/SPZ/PLY format...");

            // Fall back to SOG if available, then SPZ, then PLY
            if (hasSogAvailable) {
              // Re-enter SOG loading path by reloading the function
              // For simplicity, just reload the page without forceLoadLod
              window.location.search = "";
              return;
            }
            const fallbackUrl = hasSpzAvailable
              ? getDownloadUrl(spjId, true)
              : getDownloadUrl(spjId, false);
            const fallbackUsesSpz = hasSpzAvailable;

            try {
              if (fallbackUsesSpz) {
                const asset = await loadSpzAsPlayCanvasAsset(
                  app,
                  fallbackUrl,
                  (percent) => setLoadingStatus("Loading SPZ", percent),
                );
                gsEntity.addComponent("gsplat", { asset: asset.id });
              } else {
                const asset = new pc.Asset("gs-data", "gsplat", {
                  url: fallbackUrl,
                });
                app.assets.add(asset);
                app.assets.load(asset);
                await new Promise<void>((resolve, reject) => {
                  asset.once("load", () => resolve());
                  asset.once("error", (err: string) => reject(new Error(err)));
                });
                gsEntity.addComponent("gsplat", { asset: asset.id });
              }
              startRendering();
            } catch (fallbackError) {
              console.error("LOD fallback also failed:", fallbackError);
              loadingStatus = "Error loading scene";
            }
          }
        } else if (useSogFile) {
          // SOG: fetch SAS URLs from server, load manually to track progress
          setLoadingStatus("Loading...", 0);
          try {
            const sogResponse = await fetch(getSogUrlsEndpoint(spjId));
            if (!sogResponse.ok)
              throw new Error(`SOG URLs request failed: ${sogResponse.status}`);

            // Expected format: { "filename": { "url": "...", "size": 12345 } }
            const sogData: Record<string, { url: string; size: number }> =
              await sogResponse.json();

            // SOG files to download
            const filesToDownload = Object.entries(sogData);

            // Refined implementation with aggregator:
            const objectUrls: Record<string, string> = {};
            const fileTotals = new Map<string, number>();
            const fileLoaded = new Map<string, number>();

            // Initialize totals with known sizes from server
            let totalSizeAllFiles = 0;
            filesToDownload.forEach(([filename, data]) => {
              fileTotals.set(filename, data.size);
              fileLoaded.set(filename, 0);
              totalSizeAllFiles += data.size;
            });

            const updateProgress = () => {
              let loaded = 0;
              fileLoaded.forEach((v) => {
                loaded += v;
              });

              if (totalSizeAllFiles > 0) {
                const percent = (loaded / totalSizeAllFiles) * 100;
                setLoadingStatus("Loading...", percent * 0.9); // 0-90%
              }
            };

            const downloadFileWithXHR = (
              filename: string,
              url: string,
              knownSize: number,
            ) => {
              return new Promise<void>((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                xhr.open("GET", url);
                xhr.responseType = "blob";

                xhr.onprogress = (event) => {
                  if (event.lengthComputable) {
                    fileLoaded.set(filename, event.loaded);
                    updateProgress();
                  }
                };

                xhr.onload = () => {
                  if (xhr.status >= 200 && xhr.status < 300) {
                    objectUrls[filename] = URL.createObjectURL(xhr.response);
                    // Ensure 100% for this file
                    fileLoaded.set(filename, knownSize);
                    updateProgress();
                    resolve();
                  } else {
                    reject(new Error(`Status ${xhr.status}`));
                  }
                };

                xhr.onerror = () => reject(new Error("Network error"));
                xhr.send();
              });
            };

            await Promise.all(
              filesToDownload.map(([f, data]) =>
                downloadFileWithXHR(f, data.url, data.size),
              ),
            );

            // All downloaded
            const metaUrl = objectUrls["meta.json"];
            if (!metaUrl)
              throw new Error("meta.json not found in downloaded assets");

            setLoadingStatus("Processing...", 95);

            const asset = new pc.Asset("gs-data", "gsplat", {
              url: metaUrl,
              filename: "meta.json",
            });
            asset.options = {
              mapUrl: (filename: string) => objectUrls[filename] || filename,
            };

            app.assets.add(asset);
            app.assets.load(asset);

            await new Promise<void>((resolve, reject) => {
              asset.once("load", () => {
                setLoadingStatus("Ready", 100);
                resolve();
              });
              asset.once("error", (err: string) => {
                reject(new Error(err));
              });
            });

            gsEntity.addComponent("gsplat", { asset: asset.id });
            startRendering();
          } catch (sogError) {
            console.error("Failed to load SOG file:", sogError);
            console.error("Falling back to SPZ/PLY format...");

            // Fall back to SPZ if available, then PLY
            const fallbackUrl = hasSpzAvailable
              ? getDownloadUrl(spjId, true)
              : getDownloadUrl(spjId, false);
            const fallbackUsesSpz = hasSpzAvailable;

            try {
              if (fallbackUsesSpz) {
                const asset = await loadSpzAsPlayCanvasAsset(
                  app,
                  fallbackUrl,
                  (percent) => setLoadingStatus("Loading SPZ", percent),
                );
                gsEntity.addComponent("gsplat", { asset: asset.id });
              } else {
                const asset = new pc.Asset("gs-data", "gsplat", {
                  url: fallbackUrl,
                });
                app.assets.add(asset);
                app.assets.load(asset);
                await new Promise<void>((resolve, reject) => {
                  asset.once("load", () => resolve());
                  asset.once("error", (err: string) => reject(new Error(err)));
                });
                gsEntity.addComponent("gsplat", { asset: asset.id });
              }
              setLoadingStatus("Processing", 100);
              startRendering();
            } catch (fallbackError) {
              console.error("SOG fallback also failed:", fallbackError);
              setLoadingStatus("Error: all loading methods failed", 0);
            }
          }
          return;
        } else if (useSpzFile) {
          // For SPZ files, use our custom SPZ loader
          setLoadingStatus("Loading", 0);

          try {
            // Load and parse SPZ file, get a PlayCanvas asset
            const asset = await loadSpzAsPlayCanvasAsset(
              app,
              sceneUrl,
              (percent) => {
                setLoadingStatus("Loading", percent);
              },
            );

            console.log(
              "SPZ Asset created:",
              asset,
              "ID:",
              asset.id,
              "Resource:",
              asset.resource,
            );

            // Add gsplat component to our entity with the loaded asset ID
            gsEntity.addComponent("gsplat", { asset: asset.id });

            setLoadingStatus("Processing", 100);
            startRendering();
          } catch (spzError) {
            console.error("Failed to load SPZ file:", spzError);
            console.error("Falling back to PLY format...");

            // Try to load PLY instead
            const plyUrl = sceneUrl.replace(".spz", ".ply");
            console.log("Attempting to load PLY from:", plyUrl);

            try {
              const asset = new pc.Asset("gs-data", "gsplat", { url: plyUrl });
              app.assets.add(asset);
              app.assets.load(asset);

              await new Promise<void>((resolve, reject) => {
                asset.once("load", () => {
                  setLoadingStatus("Processing (PLY fallback)", 100);
                  resolve();
                });
                asset.once("error", (err: string) => {
                  reject(new Error(err));
                });
              });

              // Add gsEntity to scene if not already there (for SPZ fallback case)
              if (!gsEntity.parent) {
                app.root.addChild(gsEntity);
              }
              gsEntity.addComponent("gsplat", { asset: asset.id });
              startRendering();
            } catch (fallbackError) {
              console.error("PLY fallback also failed:", fallbackError);
              setLoadingStatus("Error: SPZ and PLY loading failed", 0);
            }
          }
        } else {
          // Load PLY file directly
          setLoadingStatus("Loading PLY", 0);

          try {
            // Create asset with URL
            const asset = new pc.Asset("gs-data", "gsplat", {
              url: sceneUrl,
            });

            // Add to asset registry
            app.assets.add(asset);

            // Load the asset
            app.assets.load(asset);

            // Wait for asset to load
            await new Promise<void>((resolve, reject) => {
              asset.once("load", () => {
                setLoadingStatus("Processing", 100);
                resolve();
              });
              asset.once("error", (err: string) => {
                reject(new Error(err));
              });
            });

            // Add GS component with asset
            gsEntity.addComponent("gsplat", {
              asset: asset.id,
            });

            startRendering();
          } catch (plyError) {
            console.error("Failed to load PLY file:", plyError);
            setLoadingStatus("Error loading PLY", 0);
          }
        }
      } catch (error) {
        console.error("Failed to load Gaussian Splatting scene:", error);
        setLoadingStatus("Error loading scene", 0);
      }
    };

    loadGSAsset();
  };

  onMount(() => {
    isMobile = detectMobile();
    spjId = document.getElementById("app")?.getAttribute("data-spj-id");
    const urlParams = new URLSearchParams(window.location.search);
    disableUI = urlParams.get("disableUI") === "true";
    slowLoadingTimeout = setTimeout(() => {
      showSlowLoadingMessage = true;
    }, 30000);
    initializeViewer().catch((error) => {
      console.error("Failed to load viewer", error);
    });

    // Register Service Worker for LOD streaming
    if ("serviceWorker" in navigator) {
      // Use a version query param to bypass the 5-minute cache when the user reloads the page.
      // Ideally, this should be a build hash, but Date.now() ensures we always get the latest
      // if the user refreshes, at the cost of bypassing the cache check.
      // Given the user's concern about "breaking", safety > bandwidth here.
      navigator.serviceWorker
        .register(`/sw.js?v=${Date.now()}`, { scope: "/" })
        .then((registration) => {
          console.log(
            "Service Worker registered with scope:",
            registration.scope,
          );
          // Ensure it's active immediately for this session
          if (registration.installing) {
            registration.installing.postMessage({ type: "SKIP_WAITING" });
          }
        })
        .catch((error) => {
          console.error("Service Worker registration failed:", error);
        });

      // Handle controller change (when SW claims clients)
      navigator.serviceWorker.addEventListener("controllerchange", () => {
        console.log("Service Worker controller changed");
      });
    }

    // Check WebXR support
    XRManager.isVRSupported().then((supported) => {
      xrSupported = supported;
      console.log("WebXR VR supported:", xrSupported);
    });

    // Handle window resize for PlayCanvas viewport
    const handleResize = () => {
      if (app) {
        app.resizeCanvas();
      }
    };
    window.addEventListener("resize", handleResize);

    // Cleanup resize listener
    return () => {
      window.removeEventListener("resize", handleResize);
    };
  });

  // Initialize joystick when useFPSControls becomes true on mobile
  $: if (
    sceneLoaded &&
    useFPSControls &&
    !movementJoystickManager &&
    !rotationJoystickManager &&
    movementJoystickZone &&
    rotationJoystickZone &&
    camera
  ) {
    if (isMobile) {
      movementJoystickManager = nipplejs.create({
        zone: movementJoystickZone,
        mode: "static",
        position: { left: "50px", bottom: "50px" },
        dynamicPage: true,
        restOpacity: 0.8,
      });
      rotationJoystickManager = nipplejs.create({
        zone: rotationJoystickZone,
        mode: "static",
        position: { right: "50px", bottom: "50px" },
        dynamicPage: true,
        restOpacity: 0.8,
      });
      joystickControls = new PlayCanvasJoystickControls(
        camera,
        movementJoystickManager,
        rotationJoystickManager,
      );
      if (useLodFile) {
        joystickControls.moveSpeed = 5.0; // Faster speed for LOD scenes
        joystickControls.touchPanSpeed = 0.012; // 4x default
        joystickControls.pinchZoomSpeed = 0.02; // 4x default
      }
    }
  }

  function initTour() {
    if (disableUI) {
      return;
    }
    const hasSeenTour = localStorage.getItem("hasSeenVid2SceneTour");
    if (hasSeenTour) {
      return;
    }

    tour = createTour({
      isMobile,
      isDroneMode: useFPSControls,
    });
    tour.start();
  }

  // Helper function to safely track events with umami
  function trackUmamiEvent(
    eventName: string,
    _eventProps?: Record<string, any>,
  ) {
    // Use window.umami directly with a type assertion
    const umami = (window as Window).umami;
    if (!umami) {
      return;
    }
    if (typeof umami.track === "function") {
      umami.track(eventName, { id: spjId });
    }
  }

  // Function to track share events
  function trackShareEvent(platform: string) {
    trackUmamiEvent(`Share ${platform}`);
  }

  function handleCopySuccess() {
    showCopiedMessage = true;

    // Track copy link event with umami
    trackShareEvent("Copy Link");

    if (copyMessageTimeout) clearTimeout(copyMessageTimeout);
    copyMessageTimeout = setTimeout(() => {
      showCopiedMessage = false;
    }, 2000);
  }

  onDestroy(() => {
    if (joystickControls) {
      joystickControls.destroy();
      joystickControls = null;
    }
    if (flyControls) {
      flyControls.destroy();
      flyControls = null;
    }
    if (orbitControls) {
      orbitControls.destroy();
      orbitControls = null;
    }
    if (groundPlaneIndicator) {
      groundPlaneIndicator.destroy();
      groundPlaneIndicator = null;
    }
    if (movementJoystickManager) {
      movementJoystickManager.destroy();
      movementJoystickManager = null;
    }
    if (rotationJoystickManager) {
      rotationJoystickManager.destroy();
      rotationJoystickManager = null;
    }
    if (xrManager) {
      xrManager.destroy();
      xrManager = null;
    }
    if (tour) {
      tour.complete();
    }
    if (app) {
      app.destroy();
    }
    if (modeChangeTimeout) clearTimeout(modeChangeTimeout);
    if (slowLoadingTimeout) clearTimeout(slowLoadingTimeout);
    if (copyMessageTimeout) clearTimeout(copyMessageTimeout);
  });

  // Function to toggle controls
  function toggleControls(event: Event) {
    event.preventDefault();
    useFPSControls = !useFPSControls;

    if (!showMenu) {
      showModeAlert = true;
      if (modeChangeTimeout) clearTimeout(modeChangeTimeout);

      modeChangeTimeout = setTimeout(() => {
        showModeAlert = false;
      }, 1000);
    }

    if (useFPSControls) {
      // Switch to fly controls
      document.body.setAttribute("data-show-joystick", "true");

      // Exit scene rotation mode if active
      if (sceneAlignerControls && sceneAlignerControls.isActive) {
        sceneAlignerControls.disable();
      }

      if (orbitControls) {
        orbitControls.enabled = false;
      }
      if (flyControls) {
        flyControls.enabled = true;
        // Recalculate orientation from current camera to prevent jumping
        flyControls.recalculateOrientation();
      } else {
        flyControls = new PlayCanvasFlyControls(app.mouse, camera);
        flyControls.worldUp = camera.up.clone();
      }
      // Initialize joystick controls for mobile if not already done
      if (
        isMobile &&
        !joystickControls &&
        movementJoystickManager &&
        rotationJoystickManager
      ) {
        joystickControls = new PlayCanvasJoystickControls(
          camera,
          movementJoystickManager,
          rotationJoystickManager,
        );
      }
    } else {
      // Switch to orbit controls
      document.body.removeAttribute("data-show-joystick");
      if (flyControls) {
        flyControls.enabled = false;
      }
      if (orbitControls) {
        orbitControls.enabled = true;
        // Raycast forward to find a new pivot point based on what the camera is looking at
        orbitControls.raycastAndSetPivot(true).then((success) => {
          if (!success) {
            // Raycast failed, fall back to forward point
            const fallbackPoint = getFPSCameraTarget();
            orbitControls!.pivotPoint.copy(fallbackPoint);
            orbitControls!.recalculateFromCameraAndPivot();
          }
        });
      } else {
        orbitControls = new PlayCanvasOrbitControls(
          app.mouse,
          camera,
          app.touch,
          app,
        );

        // Raycast to find initial pivot point
        orbitControls.raycastAndSetPivot(true).then((success) => {
          if (!success) {
            // Raycast failed, fall back to forward point
            const fallbackPoint = getFPSCameraTarget();
            orbitControls!.pivotPoint.copy(fallbackPoint);
            orbitControls!.recalculateFromCameraAndPivot();
          }
        });
      }
    }
  }

  function getFPSCameraTarget() {
    if (!camera) return new pc.Vec3(1, 0, 0);

    const cameraForward = camera.forward.clone();
    const cameraPosition = camera.getPosition();
    // Use a reasonable distance for the lookAt point (10 units forward from camera)
    const lookAtDistance = 10;
    const cameraLookAt = cameraPosition
      .clone()
      .add(cameraForward.mulScalar(lookAtDistance));
    return cameraLookAt;
  }

  function toggleMenu(event: Event) {
    event.preventDefault();
    showMenu = !showMenu;
    if (showMenu && showShareMenu) {
      showShareMenu = false;
    }
  }

  async function shareWithNativeAPI() {
    try {
      if (navigator.share) {
        await navigator.share({
          title: title,
          text: `Check out this 3D scene: ${title}`,
          url: window.location.href,
        });

        // Track the share event using umami after successful share
        trackShareEvent("API");

        return true;
      }
      return false;
    } catch (error) {
      if (error && error.name === "AbortError") {
        // This is expected when the user cancels the share dialog
        return true;
      }
      console.error("Error with Web Share API:", error);
      return false;
    }
  }

  function toggleShareMenu(event: Event) {
    event.preventDefault();

    // On desktop, always show the custom share menu
    if (!isMobile) {
      showShareMenu = !showShareMenu;
      if (showShareMenu && showMenu) {
        showMenu = false;
      }
      return;
    }

    // On mobile, try to use Web Share API first if available
    shareWithNativeAPI().then((succeeded) => {
      if (!succeeded) {
        // If Web Share API is not available or fails, show custom share menu
        showShareMenu = !showShareMenu;
        if (showShareMenu && showMenu) {
          showMenu = false;
        }
      }
    });
  }

  async function toggleXR(event: Event) {
    event.preventDefault();

    if (!xrManager) {
      console.error("XR Manager not initialized");
      return;
    }

    if (isInXR) {
      // Exit VR
      xrManager.endSession();
    } else {
      // Enter VR
      const success = await xrManager.startSession();
      if (!success) {
        alert(
          "Failed to start VR session. Make sure you have a VR headset connected or are using a WebXR-compatible browser.",
        );
      }
    }
  }

  let showModeAlert = false;
  let modeChangeTimeout: number;
  let disableUI = false;
</script>

<svelte:head>
  <link rel="preload" as="image" href={closeIcon} />
  <link rel="preload" as="image" href={gearIcon} />
  <link rel="preload" as="image" href={orbitalViewIcon} />
  <link rel="preload" as="image" href={droneViewIcon} />
  <link rel="preload" as="image" href={shareIcon} />
</svelte:head>

<main>
  <!-- PlayCanvas canvas will be inserted here by the app -->

  <div
    id="movement-joystick-position-zone"
    class="unselectable"
    bind:this={movementJoystickZone}
    style="position: fixed; bottom: 25px; left: 25px; width: 100px; height: 100px;"
  ></div>
  <div
    id="rotation-joystick-position-zone"
    class="unselectable"
    bind:this={rotationJoystickZone}
    style="position: fixed; bottom: 25px; right: 25px; width: 100px; height: 100px;"
  ></div>

  {#if sceneLoaded}
    <!-- Joystick zone is always in the DOM; its visibility is controlled via CSS -->

    {#if !showMenu && !showShareMenu && !disableUI}
      <button
        class="menu-button btn btn-dark btn-sm position-fixed"
        on:click={toggleMenu}
        style="opacity: 0.7;"
        in:fade={{ delay: 300, duration: 100 }}
      >
        <img
          src={gearIcon}
          height="24"
          width="24"
          alt="Settings"
          class="menu-icon"
          style="opacity: 0.7;"
        />
      </button>

      <button
        class="menu-button btn btn-dark btn-sm position-fixed"
        id="controlsButton"
        on:click={toggleControls}
        style="opacity: 0.7; top: 4rem;"
        in:fade={{ delay: 300, duration: 100 }}
      >
        {#if !isMobile}
          <Tooltip target="controlsButton" placement="left" delay={500}>
            <span style="font-size: 1.2em"
              >{useFPSControls
                ? "Switch to Orbital Controls"
                : "Switch to Drone Controls"}</span
            >
          </Tooltip>
        {/if}
        {#if useFPSControls}
          <img
            src={droneViewIcon}
            height="24"
            width="24"
            alt="Switch to Orbital Controls"
            class="menu-icon"
            style="opacity: 0.7; object-fit: contain; transform: scale(1.3);"
          />
        {:else}
          <img
            src={orbitalViewIcon}
            height="24"
            width="24"
            alt="Switch to Drone Controls"
            class="menu-icon"
            style="opacity: 0.7; transform: scale(1.15);"
          />
        {/if}
      </button>

      <!-- Share Button on the right under drone control toggle -->
      <button
        class="menu-button btn btn-dark btn-sm position-fixed"
        id="shareButton"
        on:click={toggleShareMenu}
        style="opacity: 0.7; top: 7rem; right: 1rem; display: {isShareable
          ? 'flex'
          : 'none'};"
        in:fade={{ delay: 300, duration: 100 }}
      >
        {#if !isMobile}
          <Tooltip target="shareButton" placement="left" delay={500}>
            <span style="font-size: 1.2em">Share this 3D scene</span>
          </Tooltip>
        {/if}
        <img
          src={shareIcon}
          height="24"
          width="24"
          alt="Share"
          class="menu-icon"
          style="opacity: 0.7; translate: -2px;"
        />
      </button>
    {/if}

    <!-- VR Button below share button -->
    {#if xrSupported && !disableUI}
      <button
        class="menu-button btn btn-dark btn-sm position-fixed"
        id="vrButton"
        on:click={toggleXR}
        style="opacity: 0.7; top: 10rem; right: 1rem;"
        in:fade={{ delay: 400, duration: 100 }}
      >
        {#if !isMobile}
          <Tooltip target="vrButton" placement="left" delay={500}>
            <span style="font-size: 1.2em"
              >{isInXR ? "Exit VR" : "Enter VR"}</span
            >
          </Tooltip>
        {/if}
        <img
          src={vrIcon}
          height="24"
          width="24"
          alt="Enter VR"
          class="menu-icon"
          style="opacity: 0.7;"
        />
      </button>
    {/if}

    <!-- Share Menu Panel with svelte-share-buttons-component -->
    {#if showShareMenu}
      <div
        class="menu-panel position-fixed text-light bg-dark p-3"
        transition:slide={{ duration: 300 }}
      >
        <div class="d-flex justify-content-between align-items-center mb-3">
          <h3 class="text-light px-2 mb-0">Share</h3>
          <button
            class="btn btn-sm px-2"
            on:click={() => (showShareMenu = false)}
          >
            <img
              src={closeIcon}
              height="24"
              width="24"
              alt="Close"
              class="menu-icon"
            />
          </button>
        </div>
        <div class="menu-content">
          <p class="text-light px-2 mb-3">Share this 3D scene with others:</p>
          <div
            id="share-buttons-container"
            class="d-flex flex-wrap justify-content-center"
          >
            <div
              role="button"
              tabindex="0"
              aria-label="Share on Facebook"
              on:click={() => trackShareEvent("Facebook")}
              on:keydown={(e) =>
                e.key === "Enter" || e.key === " "
                  ? trackShareEvent("Facebook")
                  : null}
            >
              <Facebook
                url={window.location.href}
                quote={`Check out this 3D scene on vid2scene: ${title}`}
              />
            </div>
            <div
              role="button"
              tabindex="0"
              aria-label="Share on X"
              on:click={() => trackShareEvent("X")}
              on:keydown={(e) =>
                e.key === "Enter" || e.key === " "
                  ? trackShareEvent("X")
                  : null}
            >
              <X
                url={window.location.href}
                text={`Check out this 3D scene on vid2scene: ${title}\n`}
              />
            </div>
            <div
              role="button"
              tabindex="0"
              aria-label="Share on LinkedIn"
              on:click={() => trackShareEvent("LinkedIn")}
              on:keydown={(e) =>
                e.key === "Enter" || e.key === " "
                  ? trackShareEvent("LinkedIn")
                  : null}
            >
              <LinkedIn url={window.location.href} />
            </div>
            <div
              role="button"
              tabindex="0"
              aria-label="Share on Reddit"
              on:click={() => trackShareEvent("Reddit")}
              on:keydown={(e) =>
                e.key === "Enter" || e.key === " "
                  ? trackShareEvent("Reddit")
                  : null}
            >
              <Reddit
                url={window.location.href}
                title={`Check out this 3D scene on vid2scene: ${title}`}
              />
            </div>
            <div
              role="button"
              tabindex="0"
              aria-label="Share on WhatsApp"
              on:click={() => trackShareEvent("WhatsApp")}
              on:keydown={(e) =>
                e.key === "Enter" || e.key === " "
                  ? trackShareEvent("WhatsApp")
                  : null}
            >
              <WhatsApp
                text={`Check out this 3D scene on vid2scene: ${title} ${window.location.href}`}
              />
            </div>
            <div
              role="button"
              tabindex="0"
              aria-label="Share on Telegram"
              on:click={() => trackShareEvent("Telegram")}
              on:keydown={(e) =>
                e.key === "Enter" || e.key === " "
                  ? trackShareEvent("Telegram")
                  : null}
            >
              <Telegram
                url={window.location.href}
                text={`Check out this 3D scene on vid2scene: ${title}`}
              />
            </div>
            <div
              role="button"
              tabindex="0"
              aria-label="Share via Email"
              on:click={() => trackShareEvent("Email")}
              on:keydown={(e) =>
                e.key === "Enter" || e.key === " "
                  ? trackShareEvent("Email")
                  : null}
            >
              <Email
                subject={`Check out this 3D scene on vid2scene: ${title}`}
                body={`Check out this 3D scene: ${window.location.href}`}
              />
            </div>
          </div>

          <div class="mt-4 d-flex justify-content-center">
            <button
              class="btn btn-outline-light copy-link-btn"
              use:copy={window.location.href}
              on:svelte-copy={handleCopySuccess}
            >
              <i class="bi bi-link-45deg me-2"></i>
              Copy shareable link
            </button>
          </div>

          <div class="message-container">
            {#if showCopiedMessage}
              <div
                class="text-center copied-message"
                transition:fade={{ duration: 200 }}
              >
                <i class="bi bi-check-circle-fill me-1"></i> Link copied to clipboard!
              </div>
            {/if}
          </div>
        </div>
      </div>
    {/if}

    <!-- Slide-out Menu -->
    {#if showMenu}
      <div
        class="menu-panel position-fixed text-light bg-dark p-3"
        transition:slide={{ duration: 300 }}
      >
        <div class="d-flex justify-content-between align-items-center mb-3">
          <h3 class="text-light px-2 mb-0">Settings</h3>
          <button class="btn btn-sm px-2" on:click={() => (showMenu = false)}>
            <img
              src={closeIcon}
              height="24"
              width="24"
              alt="Close"
              class="menu-icon"
            />
          </button>
        </div>
        <div class="menu-content">
          <div class="controls-section mb-4">
            <h4 class="text-light px-2 mb-3">Controls</h4>
            <p class="text-light px-2 mb-3">
              Current control mode: {useFPSControls ? "Drone" : "Orbital"}
            </p>
            {#if isMobile && useFPSControls}
              <ul class="list-unstyled px-2">
                <li>• Use left joystick to move camera</li>
                <li>• Use right joystick to rotate camera</li>
                <li>
                  • You can also touch and drag on the screen to rotate the
                  camera. Using two fingers will zoom and pan the camera
                </li>
              </ul>
            {:else if isMobile && !useFPSControls}
              <ul class="list-unstyled px-2">
                <li>• Tap something in the scene to focus on it</li>
                <li>• One finger drag to orbit camera</li>
                <li>• Two finger drag to pan camera</li>
                <li>• Pinch to zoom</li>
              </ul>
            {:else if !isMobile && useFPSControls}
              <ul class="list-unstyled px-2">
                <li>• Left click and drag to look around</li>
                <li>• Right click to move camera forward</li>
                <li>
                  • Press space to toggle video game-like pointerlock controls
                </li>
                <li>• W/A/S/D keys are additional controls to move camera</li>
                <li>• Shift/Control keys move camera up/down</li>
              </ul>
            {:else if !isMobile && !useFPSControls}
              <ul class="list-unstyled px-2">
                <li>
                  • Left click something in the scene to focus camera towards it
                </li>
                <li>• Left click and drag to orbit camera</li>
                <li>• Right click and drag to pan camera</li>
                <li>• Scroll wheel to zoom</li>
              </ul>
            {/if}
          </div>
          <button
            class="btn btn-primary mb-3 w-auto mx-2"
            style="opacity: 1.0;"
            on:click={toggleControls}
          >
            {#if useFPSControls}
              Switch to Orbital Controls
            {:else}
              Switch to Drone Controls
            {/if}
          </button>
          <br />
          <button
            class="btn btn-primary mb-3 w-auto mx-2"
            style="opacity: 1.0;"
            on:click={showGroundPlane}
          >
            Toggle Ground Plane
          </button>
          <br />
          {#if useLodFile}
            <button
              class="btn mb-3 w-auto mx-2"
              class:btn-warning={debugLodColorize}
              class:btn-primary={!debugLodColorize}
              style="opacity: 1.0;"
              on:click={() => {
                debugLodColorize = !debugLodColorize;
                if (app?.scene?.gsplat) {
                  app.scene.gsplat.colorizeLod = debugLodColorize;
                }
              }}
            >
              {debugLodColorize ? "Disable" : "Enable"} LOD Debug Colors
            </button>
            <br />
          {/if}
          <button
            class="btn btn-primary mb-3 w-auto mx-2"
            style="opacity: 1.0;"
            on:click={() => {
              localStorage.removeItem("hasSeenVid2SceneTour");
              showMenu = false;
              initTour();
            }}
          >
            Reset Tutorial
          </button>
          <br />
          {#if isOwner}
            <button
              class="btn mb-3"
              class:btn-danger={sceneAlignerControls &&
                sceneAlignerControls.isActive}
              class:btn-primary={!sceneAlignerControls ||
                !sceneAlignerControls.isActive}
              style="opacity: 1.0; width: 80%"
              on:click={() => toggleSceneRotationMode()}
              disabled={sceneAlignerControls && sceneAlignerControls.isActive}
            >
              Align Scene (Fix Up Direction)
            </button>
            <button
              class="btn btn-warning mb-3 w-auto mx-2"
              style="opacity: 1.0;"
              on:click={() => saveCameraInfo()}
            >
              Save Current View as Default
            </button>
          {/if}
        </div>
      </div>
    {/if}
  {/if}

  {#if !sceneLoaded}
    <div class="loading-screen">
      <!-- Background container -->
      <div class="background">
        <img
          src={previewImageUrl}
          alt=""
          class="background-image"
          aria-hidden="true"
          on:load={() => {
            backgroundLoaded = true;
          }}
          style="opacity: {backgroundLoaded ? 1 : 0};"
        />
      </div>

      <!-- Content container -->
      <div class="loading-screen-content">
        <img
          src={samusynthLogo}
          alt="vid2scene Logo"
          class="mb-3 rotating-logo"
          on:load={() => (logoLoaded = true)}
          style="opacity: {logoLoaded ? 1 : 0}; transition: opacity 0.5s ease;"
        />
        <h1
          class="display-3 {backgroundLoaded
            ? 'text-white loading-text-after-preview'
            : 'text-black'}"
        >
          {title}
        </h1>
        <p
          class="mt-2 {backgroundLoaded
            ? 'text-white loading-text-after-preview'
            : 'text-black'}"
        >
          {loadingStatus}
        </p>
        {#if showSlowLoadingMessage}
          <p
            class="mt-2 mx-2 {backgroundLoaded
              ? 'text-white loading-text-after-preview'
              : 'text-black'}"
          >
            Slow loading? For the best experience, make sure you are connected
            to a fast WiFi network. We are working on optimizing things to make
            loading faster.
          </p>
        {/if}
      </div>
    </div>
  {/if}

  {#if showModeAlert}
    <div
      class="mode-alert position-fixed top-50 start-50 translate-middle bg-dark text-light p-3 rounded"
      transition:fade={{ duration: 200 }}
    >
      Switched to {useFPSControls ? "Drone" : "Orbital"} Controls
    </div>
  {/if}

  {#if sceneAlignerControls && sceneAlignerControls.isActive}
    <div
      class="mode-alert interactive position-fixed bottom-0 start-50 translate-middle-x bg-dark text-light p-3 rounded mb-3"
      style="font-size: 1rem;"
    >
      <strong>Scene Alignment Mode</strong><br />
      <span style="font-size: 0.85rem;">
        Drag rings to align the ground plane with the scene. You may have to
        align from a few different views.<br />
        <span style="color: #ff6666;">Red (X)</span> ·
        <span style="color: #66ff66;">Green (Y)</span> ·
        <span style="color: #6666ff;">Blue (Z)</span> ·
        <span style="color: #ffff66;">Yellow (View)</span>
      </span>
      <div class="mt-2">
        <button
          class="btn btn-sm btn-success me-2"
          on:click={() => {
            if (sceneAlignerControls) {
              sceneAlignerControls.apply();
              toggleSceneRotationMode();
            }
          }}
        >
          Apply
        </button>
        <button
          class="btn btn-sm btn-warning me-2"
          on:click={() => {
            if (sceneAlignerControls) {
              sceneAlignerControls.undo();
              toggleSceneRotationMode(false);
            }
          }}
        >
          Undo
        </button>
      </div>
    </div>
  {/if}
</main>

<style>
  .rotating-logo {
    width: 200px;
    height: 200px;
    animation: rotate-sigma 1.5s infinite linear;
  }

  @keyframes rotate-sigma {
    0% {
      transform: rotate(0deg);
    }
    10% {
      transform: rotate(0deg);
      animation-timing-function: ease-in;
    }
    50% {
      transform: rotate(180deg);
      animation-timing-function: ease-out;
    }
    90% {
      transform: rotate(360deg);
    }
    100% {
      transform: rotate(360deg);
    }
  }

  .unselectable {
    -webkit-touch-callout: none;
    -webkit-user-select: none;
    -khtml-user-select: none;
    -moz-user-select: none;
    -ms-user-select: none;
    user-select: none;
  }

  #movement-joystick-position-zone {
    z-index: 1002; /* Ensure joystick is above other elements */
    display: none; /* Hidden by default on mobile */
  }

  #rotation-joystick-position-zone {
    z-index: 1002; /* Ensure joystick is above other elements */
    display: none; /* Hidden by default on mobile */
  }

  /* Show joystick when body has data-show-joystick attribute */
  :global(body[data-show-joystick]) #movement-joystick-position-zone {
    display: block !important;
  }

  :global(body[data-show-joystick]) #rotation-joystick-position-zone {
    display: block !important;
  }

  .menu-button {
    top: 1rem;
    right: 1rem;
    z-index: 1000;
    border-radius: 50%;
    width: 40px;
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.2rem;
  }

  .menu-panel {
    top: 0;
    right: 0;
    width: 100vw;
    height: auto;
    z-index: 1001;
    box-shadow: -2px 0 5px rgba(0, 0, 0, 0.2);
    opacity: 0.8;
    touch-action: manipulation;
  }

  @media (min-width: 768px) {
    .menu-panel {
      width: 768px;
    }
  }

  .loading-screen {
    position: fixed;
    top: 0;
    left: 0;
    height: 100vh;
    width: 100vw;
    overflow: hidden;
    z-index: 10;
    background-color: white;
  }

  .background {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
  }

  .background-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    overflow: hidden;
    transform: scale(1.1);
    filter: blur(8px);
  }

  .loading-screen-content {
    position: relative;
    height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
  }

  .loading-text-after-preview {
    text-shadow: 0 0 10px rgba(0, 0, 0, 1);
  }

  /* Disable scrollbars */
  :global(body) {
    margin: 0;
    overflow: hidden;
  }

  main {
    overflow: hidden;
  }

  #share-buttons-container {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 10px;
    border-radius: 50%;
    height: 40px;
  }

  .mode-alert {
    text-align: center;
    z-index: 1000;
    opacity: 0.8;
  }

  .mode-alert.interactive {
    pointer-events: auto;
  }

  /* I don't like this, but it's the way to override the default bootstrap tooltip styles */
  :global(.tooltip-inner) {
    background-color: rgb(var(--bs-dark-rgb)) !important;
  }

  :global(.tooltip-arrow::before) {
    border-left-color: rgb(var(--bs-dark-rgb)) !important;
  }

  :global(.shepherd-theme-bootstrap) {
    background-color: rgb(var(--bs-dark-rgb)) !important;
    color: var(--bs-white) !important;
    border-radius: var(--bs-border-radius) !important;
    opacity: 0.9;
    box-shadow: var(--bs-box-shadow) !important;
  }

  :global(.shepherd-theme-bootstrap .shepherd-arrow:before) {
    background-color: rgb(var(--bs-dark-rgb)) !important;
  }

  :global(.shepherd-theme-bootstrap .shepherd-button) {
    background: var(--bs-info) !important;
    border: none !important;
    border-radius: var(--bs-border-radius) !important;
    padding: 0.375rem 0.75rem !important;
    margin: 3px !important;
    color: var(--bs-white) !important;
    font-weight: var(--bs-body-font-weight) !important;
  }

  :global(.shepherd-theme-bootstrap .shepherd-button[data-role="prev"]) {
    background: var(--bs-gray-600) !important;
  }

  :global(.shepherd-theme-bootstrap .shepherd-button[data-role="prev"]:hover) {
    background: var(--bs-gray-700) !important;
  }

  :global(.shepherd-theme-bootstrap .shepherd-button:hover) {
    background: var(--bs-cyan) !important;
  }

  :global(.shepherd-theme-bootstrap .shepherd-cancel-icon) {
    color: var(--bs-gray-400) !important;
  }

  :global(.shepherd-theme-bootstrap .shepherd-text) {
    padding: 1rem !important;
    color: var(--bs-white) !important;
    font-family: var(--bs-body-font-family) !important;
    font-size: var(--bs-body-font-size) !important;
  }

  :global(.shepherd-modal-overlay-container) {
    opacity: 0.5 !important;
  }
  :global(.shepherd-theme-bootstrap .shepherd-button.shepherd-button-primary) {
    background: #6f79e6 !important;
  }

  :global(
      .shepherd-theme-bootstrap
        .shepherd-button.shepherd-button-primary:not(
          .shepherd-button-complete
        ):hover
    ) {
    background: #5761d9 !important;
  }

  :global(.shepherd-theme-bootstrap .shepherd-button.shepherd-button-complete) {
    background: linear-gradient(90deg, #5761d9, var(--bs-orange)) !important;
    font-weight: 600 !important;
  }

  :global(
      .shepherd-theme-bootstrap .shepherd-button.shepherd-button-complete:hover
    ) {
    filter: brightness(90%) !important;
    background: linear-gradient(90deg, #5761d9, var(--bs-orange)) !important;
  }

  :global(
      .shepherd-theme-bootstrap .shepherd-button.shepherd-button-secondary
    ) {
    background: var(--bs-gray-700) !important;
  }

  :global(
      .shepherd-theme-bootstrap .shepherd-button.shepherd-button-secondary:hover
    ) {
    background: var(--bs-gray-800) !important;
  }

  :global(#share-buttons-container .ssbc-button) {
    border-radius: 50% !important;
    height: 40px !important;
    padding: 0.75em !important;
  }

  :global(#share-buttons-container .ssbc-button__icon) {
    height: 16px;
    translate: 0px -4px;
  }

  .copy-link-btn {
    font-size: 1rem;
    padding: 0.5rem 1rem;
    border-radius: 0.5rem;
    transition: all 0.2s;
  }

  .copy-link-btn:hover {
    background-color: rgba(255, 255, 255, 0.2);
  }

  .copied-message {
    color: var(--bs-success);
    font-size: 0.9rem;
  }

  .message-container {
    height: 16px; /* Fixed height to accommodate the copied message */
    display: flex;
    justify-content: center;
    align-items: center;
    margin-top: 0.5rem;
  }
</style>
