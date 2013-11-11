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

(defn setup-screen [parent-element input-chan]
  (let [screen (screen/create-scrollback-screen parent-element)]
    (go
     (loop []
       (let [msg (<! input-chan)]
         ;; handle msg by invoking some screen method
         )
       (recur)))))

(defn setup-websocket [url]

  )

(defn setup-terminal
  []
  (let [screen-input-chan (chan)
        ;; setup websocket
        ;; setup resize chan
        ]
    (setup-screen (dom-utils/select 'body) screen-input-chan)
    ))

(defn init []
  (set! (.-onreadystatechange js/document)
        #(when (== (.-readyState js/document) "complete") (setup-terminal))))

(init)