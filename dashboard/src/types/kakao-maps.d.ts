// 카카오맵 JS SDK는 공식 타입 패키지가 없어서, 이 프로젝트에서 실제로 쓰는
// 만큼만 최소한으로 선언한다. namespace/Window 선언을 전부 declare global
// 안에 둬야(모듈 스코프가 아니라) 다른 파일에서 import 없이 `kakao.maps.*`
// 타입과 `window.kakao`를 바로 쓸 수 있다.
export {};

declare global {
  namespace kakao.maps {
    class LatLng {
      constructor(lat: number, lng: number);
      getLat(): number;
      getLng(): number;
    }

    class LatLngBounds {
      constructor();
      extend(latlng: LatLng): void;
    }

    interface MapOptions {
      center: LatLng;
      level?: number;
    }

    class Map {
      constructor(container: HTMLElement, options: MapOptions);
      setBounds(bounds: LatLngBounds): void;
      setCenter(latlng: LatLng): void;
      relayout(): void;
      getLevel(): number;
      setLevel(level: number): void;
    }

    interface MarkerOptions {
      position: LatLng;
      map?: Map;
      title?: string;
      image?: MarkerImage;
      zIndex?: number;
    }

    class Marker {
      constructor(options: MarkerOptions);
      setMap(map: Map | null): void;
      setPosition(latlng: LatLng): void;
      setImage(image: MarkerImage): void;
      setZIndex(zIndex: number): void;
    }

    // 관제 지도의 존(Zone) 범위 표시(2026-10-03). radius는 미터.
    interface CircleOptions {
      center: LatLng;
      radius: number;
      strokeWeight?: number;
      strokeColor?: string;
      strokeOpacity?: number;
      strokeStyle?: string;
      fillColor?: string;
      fillOpacity?: number;
    }

    class Circle {
      constructor(options: CircleOptions);
      setMap(map: Map | null): void;
      setRadius(radius: number): void;
      setPosition(latlng: LatLng): void;
    }

    class Size {
      constructor(width: number, height: number);
    }

    class Point {
      constructor(x: number, y: number);
    }

    interface MarkerImageOptions {
      offset?: Point;
    }

    class MarkerImage {
      constructor(src: string, size: Size, options?: MarkerImageOptions);
    }

    interface PolylineOptions {
      path: LatLng[];
      strokeWeight?: number;
      strokeColor?: string;
      strokeOpacity?: number;
      strokeStyle?: string;
    }

    class Polyline {
      constructor(options: PolylineOptions);
      setMap(map: Map | null): void;
      setPath(path: LatLng[]): void;
    }

    interface CustomOverlayOptions {
      position: LatLng;
      content: string | HTMLElement;
      xAnchor?: number;
      yAnchor?: number;
      zIndex?: number;
      // true면 오버레이 위 클릭이 지도로 번지지 않는다(관제 지도의 환자 요청 표시를 누를 때).
      clickable?: boolean;
    }

    class CustomOverlay {
      constructor(options: CustomOverlayOptions);
      setMap(map: Map | null): void;
      setPosition(position: LatLng): void;
      setZIndex(zIndex: number): void;
    }

    interface MouseEvent {
      latLng: LatLng;
    }

    namespace event {
      function addListener(target: Map, type: "click", handler: (event: MouseEvent) => void): void;
      function addListener(target: Map, type: "zoom_changed", handler: () => void): void;
      function addListener(target: Marker, type: "click", handler: () => void): void;
      function removeListener(target: Map, type: "click", handler: (event: MouseEvent) => void): void;
      function removeListener(target: Map, type: "zoom_changed", handler: () => void): void;
    }

    function load(callback: () => void): void;
  }

  interface Window {
    kakao: typeof kakao;
  }
}
