// ESM wrapper for the UMD JSZip bundle.
// jszip.min.js assigns JSZip to `self` in a service-worker context.
import './jszip.min.js';
const JSZip = self.JSZip;
export default JSZip;
