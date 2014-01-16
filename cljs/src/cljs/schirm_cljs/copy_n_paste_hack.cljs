(ns schirm-cljs.copy-n-paste-hack
  (:require [schirm-cljs.dom-utils :as dom-utils]))

(defn key-paste
  "Invoke f with the pasted value.

  Use this function when a CTRL-V keypress happens."
  [f]
  (let [textarea (.createElement js/document "TEXTAREA")
        focused-element (.-activeElement js/document)]
    (-> js/document .-body (.appendChild textarea))
    (.focus textarea)
    (.setTimeout js/window (fn []
                             (f (.-value textarea))
                             (.remove textarea)
                             (.focus focused-element))
                 0)
    false))

(defn setup-mouse-paste
  "Use a nearly invisible pixel-size textarea to be able to paste text.

  Set it up so that on any right click on a non-selected part of
  container, the browser 'input' contextmenu appears, with the 'paste'
  menuitem resulting in calling the paste callback function with the
  pasted value.

  Leave a 25px wide space on the left where the normal contextmenu
  appears to be able to access the 'reload' and 'inspect element'
  items."
  [container paste]
  (let [ta (dom-utils/create-element "textarea" {:class-name "paste"})]
    (-> js/document .-body (.appendChild ta))
    ;; the container is focused when pressing any key or when the terminal receives any data
    (.addEventListener ta "blur" #(set! (-> ta .-style .-display) "none"))
    ;; pasting
    (.addEventListener ta "paste" (fn [e]
                                    (.setTimeout js/window
                                                 (fn []
                                                   (paste (.-value ta))
                                                   (set! (.-value ta) "")
                                                   (.focus container))
                                                 0)))
    (.addEventListener container
                       "mousedown"
                       (fn [e]
                         (let [x (.-x e)
                               y (.-y e)
                               sel (.getSelection js/document)
                               sel-bounds (when-let [s (< 0 (.-rangeCount sel))]
                                            (-> sel (.getRangeAt 0) .getBoundingClientRect))
                               scroll-top  (-> js/document .-body .-scrollTop)
                               scroll-left (-> js/document .-body .-scrollLeft)]
                           (when (and
                                  ;; right or middle click
                                  (or (= (.-button e) 2)
                                      (= (.-button e) 1))
                                  ;; on the first 25 pixels, present the normal, non-input
                                  ;; contextmenu to allow accessing the 'reload' and 'inspect element' items
                                  (< 25 x)
                                  ;; not on a selection
                                  (if sel-bounds
                                    (or (not (< (.-left sel-bounds) x (.-right sel-bounds)))
                                        (not (< (.-top sel-bounds)  y (.-bottom sel-bounds))))
                                    true))
                             ;; display and move the pixel sized textarea to the current mouse position
                             (set! (-> ta .-style .-display) "block")
                             (set! (-> ta .-style .-top)  (+ scroll-top  y))
                             (set! (-> ta .-style .-left) (+ scroll-left x))
                             (.focus ta)
                             (.preventDefault e)))))))
