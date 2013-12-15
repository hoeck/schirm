(ns schirm-cljs.term
  (:require [cljs.core.async :as async
             :refer [<! >! chan close! sliding-buffer put! alts!]]

            [schirm-cljs.screen :as screen]
            [schirm-cljs.dom-utils :as dom-utils])

  (:require-macros [cljs.core.async.macros :as m :refer [go alt!]]))

;; (.write js/document "Hello, ClojureScript!")
;;
;; (defn test-fn [x]
;;   (print "x is" x))


;; events -> chan
;; socket-messages -> chan

(defn invoke-screen-method [screen msg]
  (let [[meth & args] msg]
    (.log js/console msg)
    (case meth
      "set-line-origin" (do (apply screen/set-origin screen args)
                            (screen/adjust screen))
      "reset"  (screen/reset screen (nth args 0))
      "resize" (screen/set-size (nth args 0))
      "insert-overwrite" (let [[line, col, string, attrs] args]
                           (screen/update-line screen
                                               line
                                               #(screen/line-insert-overwrite
                                                 %
                                                 (screen/StyledString. string
                                                                       (apply screen/->CharacterStyle args))
                                                 col
                                                 ))))))

(defn setup-screen [parent-element input-chan]
  (let [screen (screen/create-scrollback-screen parent-element)]
    (go
     (loop []
       (doseq [message (<! input-chan)]
               (invoke-screen-method screen message))
       (recur)))))

(defn setup-websocket [url in out]
  (let [ws (js/WebSocket. url)]
    (.log js/console "setup-websocket" ws)
    (set! (.-onmessage ws)
          (fn [ev]
            (if (not= "" (.-data ev))
              (put! out (.parse js/JSON (.-data ev))))))
    (go
     (loop []
       (let [msg (<! in)]
         (.log js/console (format "send msg: %s" msg))
         (.send ws msg)
         (recur))))))

(defn setup-terminal
  []
  (let [ws-send  (chan)
        ws-recv (chan)
        ws-url (format "ws://%s" (-> js/window .-location .-host))]
    (setup-screen (dom-utils/select 'body) ws-recv)
    (setup-websocket ws-url ws-send ws-recv)
    ;; (go (loop []
    ;;       (let [msg (<! ws-recv)]
    ;;         (.log js/console "-- recv via chan:" msg)
    ;;         (recur))))
    ))

(defn init []
  (.addEventListener js/document "readystatechange"
                     #(do
                        (when (== (.-readyState js/document) "complete")
                          (setup-terminal)))))

(init)
