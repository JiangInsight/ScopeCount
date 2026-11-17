#pragma once


#define SCOPECOUNT_CUT_LIBRARY
#include "../cut.cpp"



namespace prefix_admission {
using admission::Cost;
using admission::FixedPlan;
using admission::Network;
using Key=pair<U,U>;
struct LocalPlan{FixedPlan plan;vector<int> ids;Cost count=0;};
struct Decision{Cost optimum=0,service=0,build=0;U keep=0;vector<bool> bought;};
class History{
    map<Key,int> index;
    vector<Key> keyByID;
    vector<Cost> construction;
    vector<LocalPlan> history;
    map<vector<Key>,size_t> classes;
public:
    static Cost service(const FixedPlan &p,U keep){
        Cost result=5*(p.b-popcount(keep));
        for(int j=0;j<p.b;j++)if((keep>>j)&1)result+=p.add[j];
        for(auto [mask,cost]:p.ranks)if(mask&keep)result+=cost;
        return result;
    }
public:
    const vector<Key>& keys()const{return keyByID;}
    size_t observe(const vector<Key>&keys,const FixedPlan&plan){
        if(auto it=classes.find(keys);it!=classes.end()){auto &n=history[it->second].count;if(n==INT64_MAX)throw overflow_error("too many arrivals");++n;return it->second;}
        LocalPlan local{plan,{},1};
        for(size_t j=0;j<keys.size();j++){
            auto [it,fresh]=index.emplace(keys[j],int(index.size()));
            if(fresh){
                auto group=find_if(plan.cache.begin(),plan.cache.end(),[&](auto g){return (g.members>>j)&1;});
                if(group==plan.cache.end())throw logic_error("missing facility");
                construction.push_back(group->build);keyByID.push_back(keys[j]);
            }
            local.ids.push_back(it->second);
        }
        size_t id=history.size();history.push_back(move(local));classes[keys]=id;return id;
    }
    Decision solve(size_t current,bool exhaustive=false)const{
        int source=0,sink=1,first=2,next=first+int(index.size());
        struct Layout{int use,rank;};
        vector<Layout> layout;
        Cost allTree=0;
        for(const auto&c:history){
            int use=next;next+=c.plan.b;int rank=next;next+=int(c.plan.ranks.size());
            layout.push_back({use,rank});
            Cost unit=service(c.plan,admission::first_bits(c.plan.b));if(unit && c.count>(INT64_MAX/4-allTree)/unit)throw overflow_error("prefix exceeds supported price range");allTree+=c.count*unit;
        }
        if(allTree>INT64_MAX/4)throw overflow_error("unsupported price range");
        Cost inf=allTree+1;
        auto scaled=[inf](Cost cost,Cost frequency){return cost && frequency>inf/cost?inf:min(inf,cost*frequency);};
        Network net(next);
        for(size_t k=0;k<construction.size();k++)net.arc(source,first+int(k),construction[k]);
        for(size_t i=0;i<history.size();i++){
            auto&c=history[i];auto layout_i=layout[i];auto&p=c.plan;
            for(int j=0;j<p.b;j++){
                int u=layout_i.use+j;
                net.arc(source,u,scaled(5,c.count));net.arc(u,sink,scaled(p.add[j],c.count));
                net.arc(first+c.ids[j],u,inf);
            }
            int off=0;
            for(auto [mask,price]:p.ranks){
                int r=layout_i.rank+off++;net.arc(r,sink,scaled(price,c.count));
                admission::each(mask,[&](int j){net.arc(layout_i.use+j,r,inf);});
            }
        }
        Decision out;out.optimum=net.flow(source,sink);
        for(size_t k=0;k<construction.size();k++){bool active=!net.reachable(first+int(k));out.bought.push_back(active);if(active)out.build+=construction[k];}
        Cost check=out.build;
        for(size_t i=0;i<history.size();i++){
            U keep=0;
            for(int j=0;j<history[i].plan.b;j++){
                if(net.reachable(layout[i].use+j))keep|=U(1)<<j;
                else if(!out.bought[history[i].ids[j]])throw logic_error("unbuilt cache selected");
            }
            Cost v=service(history[i].plan,keep);check+=history[i].count*v;
            if(i==current){out.service=v;out.keep=keep;}
        }
        if(check!=out.optimum)throw logic_error("cut price mismatch");
        if(exhaustive){
            if(index.size()>10)throw invalid_argument("enumeration is only for small instances");
            Cost best=INT64_MAX;U maximal=0;
            for(U acquired=0;acquired<(U(1)<<index.size());acquired++){
                Cost total=0;
                for(size_t j=0;j<construction.size();j++)if((acquired>>j)&1)total+=construction[j];
                for(auto&c:history){
                    Cost bestLocal=INT64_MAX;U options=0;
                    for(int j=0;j<c.plan.b;j++)if((acquired>>c.ids[j])&1)options|=U(1)<<j;
                    for(U use=options;;use=(use-1)&options){
                        bestLocal=min(bestLocal,service(c.plan,admission::first_bits(c.plan.b)^use));
                        if(!use)break;
                    }
                    total+=bestLocal*c.count;
                }
                if(total<best){best=total;maximal=acquired;}else if(total==best)maximal|=acquired;
            }
            if(best!=out.optimum)throw logic_error("enumerated cost mismatch");
            for(size_t j=0;j<construction.size();j++)if(bool((maximal>>j)&1)!=out.bought[j])throw logic_error("canonical placement mismatch");
        }
        return out;
    }
};
}
