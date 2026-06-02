import * as pc from 'playcanvas';

// SPZ file format reader adapted for PlayCanvas

class GunzipReader {
  fileBytes: Uint8Array;
  chunkBytes: number;

  chunks: Uint8Array[];
  totalBytes: number;
  reader: ReadableStreamDefaultReader<Uint8Array>;

  constructor({
    fileBytes,
    chunkBytes = 64 * 1024,
  }: { fileBytes: Uint8Array; chunkBytes?: number }) {
    this.fileBytes = fileBytes;
    this.chunkBytes = chunkBytes;
    this.chunks = [];
    this.totalBytes = 0;

    const ds = new DecompressionStream('gzip');
    const decompressionStream = new Blob([fileBytes]).stream().pipeThrough(ds);
    this.reader = decompressionStream.getReader();
  }

  async read(numBytes: number): Promise<Uint8Array> {
    while (this.totalBytes < numBytes) {
      const { value: chunk, done: readerDone } = await this.reader.read();
      if (readerDone) {
        break;
      }

      this.chunks.push(chunk);
      this.totalBytes += chunk.length;
    }

    if (this.totalBytes < numBytes) {
      throw new Error(
        `Unexpected EOF: needed ${numBytes}, got ${this.totalBytes}`,
      );
    }

    const allBytes = new Uint8Array(this.totalBytes);
    let outOffset = 0;
    for (const chunk of this.chunks) {
      allBytes.set(chunk, outOffset);
      outOffset += chunk.length;
    }

    const result = allBytes.subarray(0, numBytes);
    this.chunks = [allBytes.subarray(numBytes)];
    this.totalBytes -= numBytes;
    return result;
  }
}

function fromHalf(val: number): number {
  const sign = (val & 0x8000) >> 15;
  const exponent = (val & 0x7c00) >> 10;
  const fraction = val & 0x03ff;

  if (exponent === 0) {
    return (sign ? -1 : 1) * Math.pow(2, -14) * (fraction / 1024);
  } else if (exponent === 0x1f) {
    return fraction ? NaN : (sign ? -1 : 1) * Infinity;
  }

  return (sign ? -1 : 1) * Math.pow(2, exponent - 15) * (1 + fraction / 1024);
}

const SH_C0 = 0.28209479177387814;

export class SpzReader {
  fileBytes: Uint8Array;
  reader: GunzipReader;

  version = -1;
  numSplats = 0;
  shDegree = 0;
  fractionalBits = 0;
  flags = 0;
  flagAntiAlias = false;
  reserved = 0;
  headerParsed = false;
  parsed = false;

  constructor({ fileBytes }: { fileBytes: Uint8Array | ArrayBuffer }) {
    this.fileBytes =
      fileBytes instanceof ArrayBuffer ? new Uint8Array(fileBytes) : fileBytes;
    this.reader = new GunzipReader({ fileBytes: this.fileBytes });
  }

  async parseHeader() {
    if (this.headerParsed) {
      throw new Error('SPZ file header already parsed');
    }

    const header = new DataView((await this.reader.read(16)).buffer);
    if (header.getUint32(0, true) !== 0x5053474e) {
      throw new Error('Invalid SPZ file');
    }
    this.version = header.getUint32(4, true);
    if (this.version < 1 || this.version > 3) {
      throw new Error(`Unsupported SPZ version: ${this.version}`);
    }

    this.numSplats = header.getUint32(8, true);
    this.shDegree = header.getUint8(12);
    this.fractionalBits = header.getUint8(13);
    this.flags = header.getUint8(14);
    this.flagAntiAlias = (this.flags & 0x01) !== 0;
    this.reserved = header.getUint8(15);
    this.headerParsed = true;
    this.parsed = false;
  }

  async parseSplats(
    centerCallback?: (index: number, x: number, y: number, z: number) => void,
    alphaCallback?: (index: number, alpha: number) => void,
    rgbCallback?: (index: number, r: number, g: number, b: number) => void,
    scalesCallback?: (
      index: number,
      scaleX: number,
      scaleY: number,
      scaleZ: number,
    ) => void,
    quatCallback?: (
      index: number,
      quatX: number,
      quatY: number,
      quatZ: number,
      quatW: number,
    ) => void,
    shCallback?: (
      index: number,
      sh1: Float32Array,
      sh2?: Float32Array,
      sh3?: Float32Array,
    ) => void,
  ) {
    if (!this.headerParsed) {
      throw new Error('SPZ file header must be parsed first');
    }
    if (this.parsed) {
      throw new Error('SPZ file already parsed');
    }
    this.parsed = true;

    // Parse centers
    if (this.version === 1) {
      const centerBytes = await this.reader.read(this.numSplats * 3 * 2);
      const centerUint16 = new Uint16Array(centerBytes.buffer);
      for (let i = 0; i < this.numSplats; i++) {
        const i3 = i * 3;
        const x = fromHalf(centerUint16[i3]);
        const y = fromHalf(centerUint16[i3 + 1]);
        const z = fromHalf(centerUint16[i3 + 2]);
        centerCallback?.(i, x, y, z);
      }
    } else if (this.version === 2 || this.version === 3) {
      const fixed = 1 << this.fractionalBits;
      const centerBytes = await this.reader.read(this.numSplats * 3 * 3);
      for (let i = 0; i < this.numSplats; i++) {
        const i9 = i * 9;
        const x =
          (((centerBytes[i9 + 2] << 24) |
            (centerBytes[i9 + 1] << 16) |
            (centerBytes[i9] << 8)) >>
            8) /
          fixed;
        const y =
          (((centerBytes[i9 + 5] << 24) |
            (centerBytes[i9 + 4] << 16) |
            (centerBytes[i9 + 3] << 8)) >>
            8) /
          fixed;
        const z =
          (((centerBytes[i9 + 8] << 24) |
            (centerBytes[i9 + 7] << 16) |
            (centerBytes[i9 + 6] << 8)) >>
            8) /
          fixed;
        centerCallback?.(i, x, y, z);
      }
    }

    // Parse alpha
    {
      const bytes = await this.reader.read(this.numSplats);
      for (let i = 0; i < this.numSplats; i++) {
        alphaCallback?.(i, bytes[i] / 255);
      }
    }

    // Parse RGB
    {
      const rgbBytes = await this.reader.read(this.numSplats * 3);
      const scale = SH_C0 / 0.15;
      for (let i = 0; i < this.numSplats; i++) {
        const i3 = i * 3;
        const r = (rgbBytes[i3] / 255 - 0.5) * scale + 0.5;
        const g = (rgbBytes[i3 + 1] / 255 - 0.5) * scale + 0.5;
        const b = (rgbBytes[i3 + 2] / 255 - 0.5) * scale + 0.5;
        rgbCallback?.(i, r, g, b);
      }
    }

    // Parse scales
    {
      const scalesBytes = await this.reader.read(this.numSplats * 3);
      for (let i = 0; i < this.numSplats; i++) {
        const i3 = i * 3;
        const scaleX = Math.exp(scalesBytes[i3] / 16 - 10);
        const scaleY = Math.exp(scalesBytes[i3 + 1] / 16 - 10);
        const scaleZ = Math.exp(scalesBytes[i3 + 2] / 16 - 10);
        scalesCallback?.(i, scaleX, scaleY, scaleZ);
      }
    }

    // Parse quaternions
    if (this.version === 3) {
      const maxValue = 1 / Math.sqrt(2);
      const quatBytes = await this.reader.read(this.numSplats * 4);
      for (let i = 0; i < this.numSplats; i++) {
        const i3 = i * 4;
        const quaternion = [0, 0, 0, 0];
        const values = [
          quatBytes[i3],
          quatBytes[i3 + 1],
          quatBytes[i3 + 2],
          quatBytes[i3 + 3],
        ];
        const combinedValues =
          values[0] + (values[1] << 8) + (values[2] << 16) + (values[3] << 24);
        const valueMask = (1 << 9) - 1;
        const largestIndex = combinedValues >>> 30;
        let remainingValues = combinedValues;
        let sumSquares = 0;

        for (let j = 3; j >= 0; --j) {
          if (j !== largestIndex) {
            const value = remainingValues & valueMask;
            const sign = (remainingValues >>> 9) & 0x1;
            remainingValues = remainingValues >>> 10;
            quaternion[j] = maxValue * (value / valueMask);
            quaternion[j] = sign === 0 ? quaternion[j] : -quaternion[j];
            sumSquares += quaternion[j] * quaternion[j];
          }
        }

        const square = 1 - sumSquares;
        quaternion[largestIndex] = Math.sqrt(Math.max(square, 0));

        quatCallback?.(
          i,
          quaternion[0],
          quaternion[1],
          quaternion[2],
          quaternion[3],
        );
      }
    } else {
      const quatBytes = await this.reader.read(this.numSplats * 3);
      for (let i = 0; i < this.numSplats; i++) {
        const i3 = i * 3;
        const quatX = quatBytes[i3] / 127.5 - 1;
        const quatY = quatBytes[i3 + 1] / 127.5 - 1;
        const quatZ = quatBytes[i3 + 2] / 127.5 - 1;
        const quatW = Math.sqrt(
          Math.max(0, 1 - quatX * quatX - quatY * quatY - quatZ * quatZ),
        );
        quatCallback?.(i, quatX, quatY, quatZ, quatW);
      }
    }

    // Parse spherical harmonics if present
    const SH_DEGREE_TO_VECS: Record<number, number> = { 1: 3, 2: 8, 3: 15 };
    if (shCallback && this.shDegree >= 1) {
      const sh1 = new Float32Array(3 * 3);
      const sh2 = this.shDegree >= 2 ? new Float32Array(5 * 3) : undefined;
      const sh3 = this.shDegree >= 3 ? new Float32Array(7 * 3) : undefined;
      const shBytes = await this.reader.read(
        this.numSplats * SH_DEGREE_TO_VECS[this.shDegree] * 3,
      );

      let offset = 0;
      for (let i = 0; i < this.numSplats; i++) {
        for (let j = 0; j < 9; ++j) {
          sh1[j] = (shBytes[offset + j] - 128) / 128;
        }
        offset += 9;
        if (sh2) {
          for (let j = 0; j < 15; ++j) {
            sh2[j] = (shBytes[offset + j] - 128) / 128;
          }
          offset += 15;
        }
        if (sh3) {
          for (let j = 0; j < 21; ++j) {
            sh3[j] = (shBytes[offset + j] - 128) / 128;
          }
          offset += 21;
        }
        shCallback?.(i, sh1, sh2, sh3);
      }
    }
  }
}

// Load SPZ file and create PlayCanvas GSplat entity
export async function loadSpzForPlayCanvas(
  url: string,
  onProgress?: (percent: number) => void
): Promise<{
  positions: Float32Array;
  colors: Float32Array;
  scales: Float32Array;
  rotations: Float32Array;
  numSplats: number;
}> {
  // Fetch the SPZ file with progress tracking
  const response = await fetch(url);

  if (!response.ok) {
    throw new Error(`Failed to fetch SPZ file: ${response.statusText}`);
  }

  const contentLength = response.headers.get('content-length');
  const total = contentLength ? parseInt(contentLength, 10) : 0;

  let loaded = 0;
  const streamReader = response.body?.getReader();
  const chunks: Uint8Array[] = [];

  if (streamReader) {
    while (true) {
      const { done, value } = await streamReader.read();

      if (done) break;

      chunks.push(value);
      loaded += value.length;

      if (total > 0 && onProgress) {
        // Report progress from 0% to 90% during download
        const downloadPercent = (loaded / total) * 90;
        onProgress(Math.min(downloadPercent, 90));
      }
    }
  }

  // Combine chunks into single array buffer
  const arrayBuffer = new Uint8Array(loaded);
  let position = 0;
  for (const chunk of chunks) {
    arrayBuffer.set(chunk, position);
    position += chunk.length;
  }

  const fileBytes = arrayBuffer;

  // Parse SPZ file (GunzipReader handles decompression automatically)
  const reader = new SpzReader({ fileBytes });
  await reader.parseHeader();

  console.log(`Loading SPZ: ${reader.numSplats} splats, SH degree: ${reader.shDegree}, version: ${reader.version}`);

  // Prepare data arrays for PlayCanvas
  const positions = new Float32Array(reader.numSplats * 3);
  const colors = new Float32Array(reader.numSplats * 4); // RGBA
  const scales = new Float32Array(reader.numSplats * 3);
  const rotations = new Float32Array(reader.numSplats * 4); // Quaternion XYZW

  // Parse all splat data
  await reader.parseSplats(
    (index, x, y, z) => {
      positions[index * 3] = x;
      positions[index * 3 + 1] = y;
      positions[index * 3 + 2] = z;
    },
    (index, alpha) => {
      colors[index * 4 + 3] = alpha;
    },
    (index, r, g, b) => {
      // SPZ reader gives: (rawByte/255 - 0.5) * (SH_C0/0.15) + 0.5
      // PlayCanvas wants: (rawByte/255 - 0.5) / 0.15
      // Algebra: result = (r - 0.5) / SH_C0
      colors[index * 4] = (r - 0.5) / SH_C0;
      colors[index * 4 + 1] = (g - 0.5) / SH_C0;
      colors[index * 4 + 2] = (b - 0.5) / SH_C0;
    },
    (index, scaleX, scaleY, scaleZ) => {
      scales[index * 3] = scaleX;
      scales[index * 3 + 1] = scaleY;
      scales[index * 3 + 2] = scaleZ;
    },
    (index, quatX, quatY, quatZ, quatW) => {
      rotations[index * 4] = quatX;
      rotations[index * 4 + 1] = quatY;
      rotations[index * 4 + 2] = quatZ;
      rotations[index * 4 + 3] = quatW;
    }
  );

  // Return the parsed data arrays
  return { positions, colors, scales, rotations, numSplats: reader.numSplats };
}

// Helper function: logit transformation for opacity
const logit = (x: number) => Math.log(x / (1 - x));

// Convert SPZ data to PlayCanvas GSplatData format
function createGSplatData(
  numSplats: number,
  positions: Float32Array,
  colors: Float32Array,
  scales: Float32Array,
  rotations: Float32Array
): any {
  // Allocate storage arrays in the format PlayCanvas expects
  const sPos = [new Float32Array(numSplats), new Float32Array(numSplats), new Float32Array(numSplats)];
  const sCol = [new Float32Array(numSplats), new Float32Array(numSplats), new Float32Array(numSplats), new Float32Array(numSplats)];
  const sScale = [new Float32Array(numSplats), new Float32Array(numSplats), new Float32Array(numSplats)];
  const sRot = [new Float32Array(numSplats), new Float32Array(numSplats), new Float32Array(numSplats), new Float32Array(numSplats)];

  // Transform data to PlayCanvas format
  for (let i = 0; i < numSplats; i++) {
    const i3 = i * 3;
    const i4 = i * 4;

    // Position - direct copy
    sPos[0][i] = positions[i3];
    sPos[1][i] = positions[i3 + 1];
    sPos[2][i] = positions[i3 + 2];

    // Color - already in correct format from parsing (f_dc coefficients)
    sCol[0][i] = colors[i4];
    sCol[1][i] = colors[i4 + 1];
    sCol[2][i] = colors[i4 + 2];

    // Opacity - apply logit transformation
    const alpha = colors[i4 + 3];
    sCol[3][i] = logit(Math.max(0.001, Math.min(0.999, alpha))); // Clamp to avoid infinity

    // Scale - convert to log space
    sScale[0][i] = Math.log(scales[i3]);
    sScale[1][i] = Math.log(scales[i3 + 1]);
    sScale[2][i] = Math.log(scales[i3 + 2]);

    // Rotation - reorder quaternion from (x,y,z,w) to PlayCanvas format
    sRot[0][i] = -rotations[i4 + 1];  // -y
    sRot[1][i] = -rotations[i4 + 2];  // -z
    sRot[2][i] = rotations[i4 + 3];   //  w
    sRot[3][i] = rotations[i4];       //  x
  }

  // Create GSplatData structure matching PlayCanvas PLY parser output
  const elements = [{
    name: 'vertex',
    count: numSplats,
    properties: [
      { name: 'x', type: 'float', byteSize: Float32Array.BYTES_PER_ELEMENT, storage: sPos[0] },
      { name: 'y', type: 'float', byteSize: Float32Array.BYTES_PER_ELEMENT, storage: sPos[1] },
      { name: 'z', type: 'float', byteSize: Float32Array.BYTES_PER_ELEMENT, storage: sPos[2] },
      { name: 'f_dc_0', type: 'float', byteSize: Float32Array.BYTES_PER_ELEMENT, storage: sCol[0] },
      { name: 'f_dc_1', type: 'float', byteSize: Float32Array.BYTES_PER_ELEMENT, storage: sCol[1] },
      { name: 'f_dc_2', type: 'float', byteSize: Float32Array.BYTES_PER_ELEMENT, storage: sCol[2] },
      { name: 'opacity', type: 'float', byteSize: Float32Array.BYTES_PER_ELEMENT, storage: sCol[3] },
      { name: 'scale_0', type: 'float', byteSize: Float32Array.BYTES_PER_ELEMENT, storage: sScale[0] },
      { name: 'scale_1', type: 'float', byteSize: Float32Array.BYTES_PER_ELEMENT, storage: sScale[1] },
      { name: 'scale_2', type: 'float', byteSize: Float32Array.BYTES_PER_ELEMENT, storage: sScale[2] },
      { name: 'rot_0', type: 'float', byteSize: Float32Array.BYTES_PER_ELEMENT, storage: sRot[0] },
      { name: 'rot_1', type: 'float', byteSize: Float32Array.BYTES_PER_ELEMENT, storage: sRot[1] },
      { name: 'rot_2', type: 'float', byteSize: Float32Array.BYTES_PER_ELEMENT, storage: sRot[2] },
      { name: 'rot_3', type: 'float', byteSize: Float32Array.BYTES_PER_ELEMENT, storage: sRot[3] }
    ]
  }];

  // Return object matching GSplatData structure (we'll use the constructor if available)
  // For now, return a plain object that mimics GSplatData
  return {
    elements,
    comments: ['Converted from SPZ format'],
    isCompressed: false,
    // Add methods that PlayCanvas expects
    reorderData: function () {
      // Already in correct order
    }
  };
}

// Main loader function that creates PlayCanvas GSplatResource from SPZ
export async function loadSpzAsPlayCanvasAsset(
  app: pc.Application,
  url: string,
  onProgress?: (percent: number) => void
): Promise<pc.Asset> {
  console.log('Loading SPZ file:', url);

  const { positions, colors, scales, rotations, numSplats } = await loadSpzForPlayCanvas(url, onProgress);

  console.log(`Loaded SPZ: ${numSplats} splats`);

  // Create GSplatData structure
  const gsplatData = createGSplatData(numSplats, positions, colors, scales, rotations);

  console.log('GSplatData created:', gsplatData);

  // Try to use PlayCanvas GSplatData constructor if available
  // @ts-ignore - GSplatData may not be exposed in types
  const GSplatDataClass = pc.GSplatData || (typeof GSplatData !== 'undefined' ? GSplatData : null);

  let data;
  if (GSplatDataClass) {
    console.log('Using GSplatData constructor');
    data = new GSplatDataClass(gsplatData.elements, gsplatData.comments);
  } else {
    console.log('GSplatData constructor not found, using plain object');
    data = gsplatData;
  }

  // Create GSplatResource
  // @ts-ignore - GSplatResource may not be exposed in types
  const GSplatResourceClass = pc.GSplatResource || (typeof GSplatResource !== 'undefined' ? GSplatResource : null);

  if (!GSplatResourceClass) {
    throw new Error('GSplatResource not available in PlayCanvas. This may require a newer version.');
  }

  console.log('Creating GSplatResource with device:', app.graphicsDevice, 'data:', data);
  const resource = new GSplatResourceClass(app.graphicsDevice, data);
  console.log('GSplatResource created:', resource);

  // Create an asset that wraps this resource
  const asset = new pc.Asset('spz-gaussian-splat', 'gsplat', null);
  asset.resource = resource;
  asset.loaded = true;

  app.assets.add(asset);

  console.log('Asset added to registry, ID:', asset.id);

  return asset;
}


